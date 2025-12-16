import json
import logging
from core.auxiliary import (
    execute_queries,
    fill_prompt_with_interview,
    chat_to_string
)
from io import BytesIO
from base64 import b64decode
from openai import OpenAI


class LLMAgent(object):
    """ Class to manage LLM-based agents. """
    def __init__(self, api_key, timeout:int=30, max_retries:int=3):
        self.client = OpenAI(api_key=api_key, timeout=timeout, max_retries=max_retries)
        logging.info("OpenAI client instantiated. Should happen only once!")

    def load_parameters(self, parameters:dict):
        """ Load interview guidelines for prompt construction. """
        self.parameters = parameters

    def transcribe(self, audio) -> str:
        """ Transcribe audio file. """
        audio_file = BytesIO(b64decode(audio))
        audio_file.name = "audio.webm"

        response = self.client.audio.transcriptions.create(
          model="whisper-1",
          file=audio_file,
          language="en" # English language input
        )
        return response.text

    def construct_query(self, tasks:list, history:list, user_message:str=None) -> dict:
        """
        Construct OpenAI API completions query,
        defaults to `gpt-4o-mini` model, 300 token answer limit, and temperature of 0.
        For details see https://platform.openai.com/docs/api-reference/completions.
        """
        return {
            task: {
                "messages": [{
                    "role":"user",
                    "content": fill_prompt_with_interview(
                        self.parameters[task]['prompt'],
                        self.parameters['interview_plan'],
                        history,
                        user_message=user_message
                    )
                }],
                "model": self.parameters[task].get('model', 'gpt-4o-mini'),
                "max_tokens": self.parameters[task].get('max_tokens', 300),
                "temperature": self.parameters[task].get('temperature', 0)
            } for task in tasks
        }

    def review_answer(self, message:str, history:list) -> bool:
        """ Moderate answers: Are they on topic? """
        response = execute_queries(
            self.client.chat.completions.create,
            self.construct_query(['moderator'], history, message)
        )
        return "yes" in response["moderator"].lower()

    def review_question(self, next_question:str) -> bool:
        """ Moderate questions: Are they flagged by the moderation endpoint? """
        response = self.client.moderations.create(
            model="omni-moderation-latest",
            input=next_question,
        )
        return response.to_dict()["results"][0]["flagged"]

    def probe_within_topic(self, history:list) -> str:
        """ Return next 'within-topic' probing question. """
        response = execute_queries(
            self.client.chat.completions.create,
            self.construct_query(['probe'], history)
        )
        return response['probe']

    def transition_topic(self, history:list) -> tuple[str, str]:
        """
        Determine next interview question transition from one topic
        cluster to the next. If have defined `summarize` model in parameters
        will also get summarization of interview thus far.
        """
        summarize = self.parameters.get('summarize')
        tasks = ['summary','transition'] if summarize else ['transition']
        response = execute_queries(
            self.client.chat.completions.create,
            self.construct_query(tasks, history)
        )
        return response['transition'], response.get('summary', '')

    def survey_step(self, state: dict, survey_definition: dict, last_user_message: str) -> dict:
        """
        Conversational survey helper that asks the next question and interprets the answer.
        """
        question_map = {q["id"]: q for q in survey_definition.get("questions", [])}
        current_question = question_map.get(state.get("current_question_id"))
        eligible_questions = [
            {
                "id": q["id"],
                "text": q.get("text"),
                "options": q.get("options", []),
                "type": q.get("type")
            }
            for q in survey_definition.get("questions", [])
            if state.get("question_status", {}).get(q["id"]) not in {"answered", "skipped"}
        ]
        system_prompt = (
            "You are assisting with a deterministic survey engine."
            " Always keep the conversation concise and friendly."
            " You must obey these hard rules:\n"
            "- NEVER invent a question. Only use questions provided in the survey definition.\n"
            "- NEVER repeat a question that is already answered or skipped.\n"
            "- If the user response is unclear for the current question, set need_clarification=true and ask one clarification question that still targets the same question id.\n"
            "- Only choose next_question_id from the allowed questions list provided.\n"
            "- If you are staying on the same question for clarification, keep next_question_id equal to that question's id.\n"
            "- Parsed answers for choice questions must be one of the provided options. Multi-select answers should be a JSON list of provided options.\n"
            "- If the user asks to skip, set parsed_answer.value to SKIP.\n"
            "- When you move forward, propose the next question in the survey order from the allowed list."
        )

        history_text = chat_to_string([
            {"content": h.get("content"), "type": "question" if h.get("role") == "assistant" else "answer", "topic_idx": 1}
            for h in state.get("history", [])
        ])
        current_question_text = current_question.get("text") if current_question else ""
        current_options = current_question.get("options", []) if current_question else []
        payload = {
            "survey_title": survey_definition.get("title"),
            "survey_intro": survey_definition.get("intro"),
            "current_question": {"id": state.get("current_question_id"), "text": current_question_text, "options": current_options},
            "remaining_questions": eligible_questions,
            "answers_so_far": state.get("answers", {}),
            "last_user_message": last_user_message,
            "history": history_text,
        }

        user_message_prompt = (
            "You are running a survey titled '{survey_title}'. "
            "Current question: {current_question}. Options: {current_options}.\n"
            "Remaining eligible questions: {remaining_questions}.\n"
            "Answers so far: {answers_so_far}.\n"
            "Last user message: {last_user_message}.\n"
            "History: {history}.\n"
            "Return only JSON following this schema:\n"
            "{{\n"
            "  \"parsed_answer\": {{\"question_id\": \"<current question id>\", \"value\": <value>, \"confidence\": <0-1 number>, \"notes\": \"optional short\"}},\n"
            "  \"need_clarification\": <true|false>,\n"
            "  \"clarification_question\": <null or string>,\n"
            "  \"next_question_id\": \"<one of remaining questions ids>\",\n"
            "  \"assistant_question_text\": \"conversational version of the next question to display\",\n"
            "  \"reasoning_brief\": \"short reasoning for validation (not shown to user)\"\n"
            "}}"
        ).format(
            survey_title=payload["survey_title"],
            current_question=payload["current_question"],
            current_options=current_options,
            remaining_questions=eligible_questions,
            answers_so_far=json.dumps(payload["answers_so_far"]),
            last_user_message=last_user_message,
            history=history_text,
        )

        response = self.client.chat.completions.create(
            model="gpt-4o-mini",
            response_format={"type": "json_object"},
            temperature=0,
            max_tokens=500,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_message_prompt},
            ],
        )
        try:
            content = response.choices[0].message.content
            return json.loads(content)
        except Exception as e:
            logging.error(f"Failed to parse survey_step response: {e}")
            return {
                "parsed_answer": {
                    "question_id": state.get("current_question_id"),
                    "value": "SKIP",
                    "confidence": 0,
                    "notes": "fallback"
                },
                "need_clarification": True,
                "clarification_question": current_question_text or "Could you clarify your answer?",
                "next_question_id": state.get("current_question_id"),
                "assistant_question_text": current_question_text or "",
                "reasoning_brief": "fallback",
            }
