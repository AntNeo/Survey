SURVEYS = {
    "CULTURE_DISCRIMINATION": {
        "title": "Discrimination & Bias",
        "intro": "Thanks for taking a few minutes. There are no right or wrong answers, and you can skip any question.",
        "questions": [
            {"id": "Q1", "type": "single_choice", "text": "In the past year, have you been discriminated against for any aspect of your identity?", "options": ["Yes", "No", "Prefer not to say"], "save_as": "q1"},
            {"id": "Q2", "type": "multi_choice", "text": "If you have been discriminated against, please select the source of the discrimination.", "options": ["Manager", "Colleague", "Customer/Client", "Policy/Process", "Other", "Prefer not to say"], "condition": {"var": "q1", "equals": "Yes"}, "save_as": "q2"},
            {"id": "Q3", "type": "single_choice", "text": "In the past year, have you witnessed discrimination against anyone else in the organisation?", "options": ["Yes", "No", "Not sure"], "save_as": "q3"},
            {"id": "Q4", "type": "multi_choice", "text": "If you have witnessed discrimination, please select the source of the discrimination.", "options": ["Manager", "Colleague", "Customer/Client", "Policy/Process", "Other", "Not sure", "Prefer not to say"], "condition": {"var": "q3", "equals": "Yes"}, "save_as": "q4"},
            {"id": "Q5", "type": "likert_5", "text": "This company takes active steps to prevent discrimination in the workplace.", "options": ["Strongly agree", "Agree", "Neither agree nor disagree", "Disagree", "Strongly disagree"], "save_as": "q5"},
            {"id": "Q6", "type": "single_choice", "text": "Do you feel comfortable addressing issues of discrimination or bias, regardless of your position or seniority?", "options": ["Yes", "No"], "save_as": "q6"},
            {"id": "Q7", "type": "free_text", "text": "Have we missed any social / cultural / demographic causes of discrimination you believe are important? If so, please let us know what they are.", "save_as": "q7"}
        ],
        "end_message": "The survey is complete. Please proceed to the next page.---END---",
        "off_topic_message": "Let's stick with the current survey question. Could you answer the question directly or say if you'd like to skip it?"
    }
}
