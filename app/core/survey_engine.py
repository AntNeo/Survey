from copy import deepcopy
from typing import Dict, List, Optional

from core.agent import LLMAgent


class SurveyEngine:
    """Deterministic survey flow with LLM-assisted phrasing and parsing."""

    def __init__(self, db, agent: LLMAgent, surveys: dict):
        self.db = db
        self.agent = agent
        self.surveys = surveys

    def _initial_state(self, session_id: str, survey_id: str, survey_definition: dict) -> dict:
        return {
            "session_id": session_id,
            "survey_id": survey_id,
            "answers": {},
            "question_status": {q["id"]: "unasked" for q in survey_definition["questions"]},
            "current_question_id": None,
            "history": [],
            "terminated": False,
        }

    def _load_state(self, session_id: str) -> dict:
        return self.db.load_remote_session(session_id)

    def _save_state(self, state: dict):
        self.db.update_remote_session(state["session_id"], state)

    def _append_history(self, state: dict, role: str, content: str, question_id: Optional[str] = None):
        state["history"].append({
            "role": role,
            "content": content,
            "question_id": question_id,
        })

    def _get_question_map(self, survey_definition: dict) -> Dict[str, dict]:
        return {q["id"]: q for q in survey_definition.get("questions", [])}

    def _is_condition_met(self, question: dict, answers: dict) -> bool:
        condition = question.get("condition")
        if not condition:
            return True
        stored = answers.get(condition.get("var"))
        if stored is None:
            return False
        if isinstance(stored, list):
            return condition.get("equals") in stored
        return stored == condition.get("equals")

    def _mark_conditionally_skipped(self, state: dict, survey_definition: dict):
        question_map = self._get_question_map(survey_definition)
        for question_id, status in list(state["question_status"].items()):
            if status != "unasked":
                continue
            question = question_map.get(question_id)
            if not question:
                continue
            if not self._is_condition_met(question, state["answers"]):
                state["question_status"][question_id] = "skipped"

    def _deterministic_next_question(self, state: dict, survey_definition: dict) -> Optional[str]:
        questions = survey_definition.get("questions", [])
        question_ids = [q["id"] for q in questions]
        current_idx = -1
        if state.get("current_question_id") in question_ids:
            current_idx = question_ids.index(state["current_question_id"])
        self._mark_conditionally_skipped(state, survey_definition)
        for q in questions[current_idx + 1:]:
            status = state["question_status"].get(q["id"])
            if status in {"answered", "skipped"}:
                continue
            if not self._is_condition_met(q, state["answers"]):
                state["question_status"][q["id"]] = "skipped"
                continue
            return q["id"]
        return None

    def _eligible_questions(self, state: dict, survey_definition: dict) -> List[dict]:
        self._mark_conditionally_skipped(state, survey_definition)
        eligible = []
        for question in survey_definition.get("questions", []):
            status = state["question_status"].get(question["id"])
            if status in {"answered", "skipped"}:
                continue
            if not self._is_condition_met(question, state["answers"]):
                state["question_status"][question["id"]] = "skipped"
                continue
            eligible.append(question)
        return eligible

    def _render_intro_and_question(self, survey_definition: dict, question: dict) -> str:
        return f"{survey_definition.get('intro', '').strip()}\n\n{question['text']}"

    def _normalize_answer(self, question: dict, parsed_value):
        question_type = question.get("type")
        options = question.get("options", [])
        if parsed_value == "SKIP":
            return "SKIP", True, False
        if question_type == "free_text":
            if isinstance(parsed_value, str):
                return parsed_value, True, False
            return "", False, True
        if question_type == "multi_choice":
            if isinstance(parsed_value, str):
                parsed_value = [v.strip() for v in parsed_value.split(",") if v.strip()]
            if isinstance(parsed_value, list) and all(opt in options for opt in parsed_value):
                return parsed_value, True, False
            return [], False, True
        if isinstance(parsed_value, str) and parsed_value in options:
            return parsed_value, True, False
        return "", False, True

    def _store_answer(self, state: dict, question: dict, normalized_value):
        save_as = question.get("save_as", question["id"])
        state["answers"][save_as] = normalized_value
        status = "skipped" if normalized_value == "SKIP" else "answered"
        state["question_status"][question["id"]] = status

    def begin_session(self, session_id: str, survey_id: str) -> dict:
        survey_definition = self.surveys[survey_id]
        state = self._initial_state(session_id, survey_id, survey_definition)
        next_question_id = self._deterministic_next_question(state, survey_definition)
        if not next_question_id:
            state["terminated"] = True
            message = survey_definition.get("end_message", "Survey complete.")
            self._append_history(state, "assistant", message)
            self._save_state(state)
            return {"session_id": session_id, "interview_id": survey_id, "message": message}
        question = self._get_question_map(survey_definition)[next_question_id]
        state["current_question_id"] = next_question_id
        state["question_status"][next_question_id] = "asked"
        message = self._render_intro_and_question(survey_definition, question)
        self._append_history(state, "assistant", message, question_id=next_question_id)
        self._save_state(state)
        return {"session_id": session_id, "interview_id": survey_id, "message": message}

    def _moderate_answer(self, survey_definition: dict, message: str, history: list) -> bool:
        if message is None:
            return True
        if not survey_definition.get("moderate_answers"):
            return True
        return self.agent.review_answer(message, history)

    def _handle_clarification(self, state: dict, question_id: str, clarification_text: str) -> dict:
        self._append_history(state, "assistant", clarification_text, question_id=question_id)
        self._save_state(state)
        return {"session_id": state["session_id"], "message": clarification_text}

    def _off_topic_response(self, state: dict, survey_definition: dict) -> dict:
        reminder = survey_definition.get(
            "off_topic_message",
            "Please respond to the current survey question or let me know if you'd like to skip."
        )
        self._append_history(state, "assistant", reminder, question_id=state.get("current_question_id"))
        self._save_state(state)
        return {"session_id": state["session_id"], "message": reminder}

    def next_step(self, session_id: str, survey_id: str, user_message: Optional[str] = None) -> dict:
        survey_definition = self.surveys[survey_id]
        state = self._load_state(session_id)
        if not state:
            return self.begin_session(session_id, survey_id)
        if state.get("terminated"):
            return {"session_id": session_id, "message": survey_definition.get("end_message", "Survey complete.")}
        self._mark_conditionally_skipped(state, survey_definition)
        if not self._moderate_answer(survey_definition, user_message, state.get("history", [])):
            return self._off_topic_response(state, survey_definition)

        question_map = self._get_question_map(survey_definition)
        current_question = question_map.get(state.get("current_question_id"))
        if not current_question:
            state["terminated"] = True
            message = survey_definition.get("end_message", "Survey complete.")
            self._append_history(state, "assistant", message)
            self._save_state(state)
            return {"session_id": session_id, "message": message}

        self._append_history(state, "user", user_message or "", question_id=current_question.get("id"))
        llm_state = deepcopy(state)
        llm_state.pop("terminated", None)
        response = self.agent.survey_step(llm_state, survey_definition, user_message or "")

        parsed_answer = response.get("parsed_answer", {}) if isinstance(response, dict) else {}
        parsed_value = parsed_answer.get("value")
        normalized_value, valid, needs_clarification = self._normalize_answer(current_question, parsed_value)
        need_clarification = response.get("need_clarification") or needs_clarification

        if not valid and not need_clarification:
            need_clarification = True

        if need_clarification:
            clarification_text = response.get("clarification_question") or current_question.get("text")
            return self._handle_clarification(state, current_question["id"], clarification_text)

        if parsed_answer.get("question_id") != current_question["id"]:
            parsed_answer["question_id"] = current_question["id"]

        self._store_answer(state, current_question, normalized_value)
        next_question_id = response.get("next_question_id") if isinstance(response, dict) else None
        allowed_questions = [q["id"] for q in self._eligible_questions(state, survey_definition)]
        deterministic_next = self._deterministic_next_question(state, survey_definition)
        if next_question_id not in allowed_questions:
            next_question_id = deterministic_next
        if not next_question_id:
            state["terminated"] = True
            message = survey_definition.get("end_message", "Survey complete.")
            self._append_history(state, "assistant", message)
            self._save_state(state)
            return {"session_id": session_id, "message": message}

        state["current_question_id"] = next_question_id
        state["question_status"][next_question_id] = "asked"
        next_question = question_map[next_question_id]
        assistant_question_text = response.get("assistant_question_text") if isinstance(response, dict) else None
        if not assistant_question_text:
            assistant_question_text = next_question.get("text")
        self._append_history(state, "assistant", assistant_question_text, question_id=next_question_id)
        self._save_state(state)
        return {"session_id": session_id, "message": assistant_question_text}

    def describe_state(self, session_id: str) -> dict:
        return self._load_state(session_id)
