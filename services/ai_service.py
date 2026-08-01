"""
AI service — IBM watsonx.ai Granite foundation model.

Uses the ibm-watsonx-ai SDK (ibm_watsonx_ai.foundation_models).
For every user message the service:
  1. Builds a structured mentor prompt from conversation history.
  2. Calls the Granite model via the watsonx.ai text-generation endpoint.
  3. Parses the model output into five mentor sections:
       • Problem Identification
       • Technology Suggestions
       • Required Components
       • Innovation Improvements
       • Development Roadmap
  4. Falls back to returning the raw text if parsing is not applicable
     (e.g. clarifying questions, follow-ups).
"""

from __future__ import annotations

import logging
import re
from typing import List, Dict

from flask import current_app

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Section headers the Granite model is instructed to use
# ---------------------------------------------------------------------------
SECTION_LABELS = [
    "PROBLEM IDENTIFICATION",
    "TECHNOLOGY SUGGESTIONS",
    "REQUIRED COMPONENTS",
    "INNOVATION IMPROVEMENTS",
    "DEVELOPMENT ROADMAP",
]


class AIService:
    """Stateless wrapper around the IBM watsonx.ai Granite chat/generation API."""

    # -----------------------------------------------------------------------
    # Stage-specific context injected into every prompt
    # -----------------------------------------------------------------------
    STAGE_HINTS: Dict[str, str] = {
        "ideation": (
            "The user is in the IDEATION stage. "
            "Focus on expanding thinking, questioning assumptions, "
            "and exploring problem-market fit."
        ),
        "prototype": (
            "The user is in the PROTOTYPING stage. "
            "Focus on MVP scope, technical feasibility, "
            "feedback loops, and rapid iteration."
        ),
        "scale": (
            "The user is in the SCALING stage. "
            "Focus on growth levers, operational efficiency, "
            "team building, and metric-driven decisions."
        ),
    }

    # -----------------------------------------------------------------------
    # Structured-analysis trigger: use this prompt when the user describes
    # an idea (first message or when the history is short).
    # -----------------------------------------------------------------------
    ANALYSIS_INSTRUCTION = """
You are Aria, an expert AI Innovation Mentor powered by IBM Granite.

A user has presented a new project idea.

Provide a complete technical analysis using EXACTLY the following format:

PROJECT OVERVIEW

PROBLEM IDENTIFICATION

RECOMMENDED TECHNOLOGIES

REQUIRED HARDWARE & SOFTWARE COMPONENTS

SYSTEM ARCHITECTURE

IMPLEMENTATION PLAN

INNOVATION IMPROVEMENTS

PRACTICAL APPLICATIONS

FUTURE ENHANCEMENTS

NEXT RECOMMENDED ACTION

Do not ask questions unless absolutely necessary.
Provide practical, student-friendly, low-cost recommendations.
Prefer IBM technologies whenever appropriate.
Explain the reason behind every recommendation.
Be concise, professional, and solution-oriented.
""".strip()

    # -----------------------------------------------------------------------
    # Conversational follow-up prompt (after the first exchange)
    # -----------------------------------------------------------------------
    FOLLOWUP_INSTRUCTION = """
You are Aria, an expert AI Innovation Mentor powered by IBM Granite.

Your mission is to mentor students, innovators, and startup teams in transforming ideas into practical AI-powered solutions.

Rules:
1. Always provide practical technical guidance before asking any questions.
2. Assume the user's idea is valid unless critical information is missing.
3. Recommend realistic, low-cost, and student-friendly hardware and software whenever possible.
4. Prefer IBM technologies such as watsonx.ai, Granite models, IBM Cloud, and IBM services whenever they are relevant.
5. Suggest complete solution architectures instead of only listing technologies.
6. Explain why each recommended technology or component is suitable.
7. Recommend implementation steps in the correct development order.
8. Suggest innovative features that make the project stand out in competitions.
9. Recommend future enhancements that could make the solution industry-ready.
10. Never ask more than ONE clarification question, and only if absolutely necessary.
11. Avoid generic answers. Every response should be tailored to the user's project.
12. If the user asks for a project idea or solution, always respond using the following format:

PROJECT OVERVIEW:
Briefly describe the project idea.

PROBLEM IDENTIFICATION:
Explain the real-world problem being solved.

RECOMMENDED TECHNOLOGIES:
List the most suitable AI models, IBM services, programming languages, frameworks, sensors, and hardware with a one-line reason for each.

SYSTEM ARCHITECTURE:
Explain how all modules interact from input to output.

IMPLEMENTATION PLAN:
Step-by-step development plan.

INNOVATION IMPROVEMENTS:
Suggest unique features that increase the project's impact.

PRACTICAL APPLICATIONS:
Mention industries or real-world use cases.

CHALLENGES & SOLUTIONS:
Mention possible implementation challenges and how to overcome them.

FUTURE ENHANCEMENTS:
Suggest advanced features using AI, IoT, Edge AI, Cloud, or Generative AI.

NEXT RECOMMENDED ACTION:
Give exactly ONE practical task the user should perform next.

Be technically accurate, concise, encouraging, and solution-oriented.
Your goal is to act like an experienced hackathon mentor rather than a general chatbot.
""".strip()

    # -----------------------------------------------------------------------
    # Public API (matches the signature expected by routes/mentor.py)
    # -----------------------------------------------------------------------
    def get_response(self, history: List[Dict[str, str]], stage: str = "ideation") -> str:
        """
        Generate an AI mentor response using IBM watsonx.ai Granite.

        :param history:  Full conversation so far as a list of
                         {"role": "user"|"assistant", "content": "..."} dicts.
                         The last entry is always the newest user message.
        :param stage:    Current innovation stage (ideation | prototype | scale).
        :returns:        Formatted mentor reply string.
        """
        cfg = current_app.config

        api_key    = cfg.get("WATSONX_API_KEY", "")
        project_id = cfg.get("WATSONX_PROJECT_ID", "")
        url        = cfg.get("WATSONX_URL", "https://us-south.ml.cloud.ibm.com")

        if not api_key or not project_id:
            return (
                "AI service unavailable — WATSONX_API_KEY and WATSONX_PROJECT_ID "
                "must be set in your .env file."
            )

        try:
            from ibm_watsonx_ai import APIClient, Credentials
            from ibm_watsonx_ai.foundation_models import ModelInference
            from ibm_watsonx_ai.metanames import GenTextParamsMetaNames as GenParams
        except ImportError:
            logger.error("ibm-watsonx-ai package not installed. Run: pip install ibm-watsonx-ai")
            return "AI service unavailable — ibm-watsonx-ai package not installed."

        # ----------------------------------------------------------------
        # Choose instruction block based on conversation depth
        # ----------------------------------------------------------------
        user_turns = sum(1 for m in history if m["role"] == "user")
        is_first_idea = user_turns <= 1
        instruction = (
            self.ANALYSIS_INSTRUCTION if is_first_idea else self.FOLLOWUP_INSTRUCTION
        )

        stage_hint = self.STAGE_HINTS.get(stage, "")
        prompt = self._build_prompt(instruction, stage_hint, history)

        # ----------------------------------------------------------------
        # Watsonx.ai model call
        # ----------------------------------------------------------------
        try:
            credentials = Credentials(url=url, api_key=api_key)
            client = APIClient(credentials=credentials, project_id=project_id)

            model = ModelInference(
                model_id=cfg.get("WATSONX_MODEL_ID", "ibm/granite-13b-instruct-v2"),
                api_client=client,
            )

            params = {
                GenParams.MAX_NEW_TOKENS: cfg.get("AI_MAX_TOKENS", 1024),
                GenParams.MIN_NEW_TOKENS: 50,
                GenParams.TEMPERATURE:    0.7,
                GenParams.TOP_P:          0.9,
                GenParams.REPETITION_PENALTY: 1.1,
                GenParams.STOP_SEQUENCES: ["Human:", "User:"],
            }

            result = model.generate_text(prompt=prompt, params=params)
            raw_text = result.strip() if isinstance(result, str) else str(result).strip()

        except Exception as exc:
            logger.exception("watsonx.ai API error: %s", exc)
            return f"I encountered an issue reaching IBM watsonx.ai: {exc}"

        # ----------------------------------------------------------------
        # Post-process: format structured sections if present
        # ----------------------------------------------------------------
        return self._format_response(raw_text)

    # -----------------------------------------------------------------------
    # Private helpers
    # -----------------------------------------------------------------------
    def _build_prompt(
        self,
        instruction: str,
        stage_hint: str,
        history: List[Dict[str, str]],
    ) -> str:
        """Assemble the full text prompt for Granite."""
        lines: List[str] = [instruction]
        if stage_hint:
            lines += ["", f"[Context: {stage_hint}]"]
        lines.append("")
        for msg in history:
            role = "User" if msg["role"] == "user" else "Aria"
            lines.append(f"{role}: {msg['content']}")
        lines += ["", "Aria:"]
        return "\n".join(lines)

    def _format_response(self, text: str) -> str:
        """
        If the model returned all five structured sections, reformat them
        with clear visual separators. Otherwise return the raw text as-is.
        """
        found = [lbl for lbl in SECTION_LABELS if lbl in text.upper()]
        if len(found) < 3:          # not a structured response — return as-is
            return text

        output_parts: List[str] = []
        # Split on any of the section headers (case-insensitive)
        pattern = r"(?i)(" + "|".join(re.escape(lbl) for lbl in SECTION_LABELS) + r")\s*:"
        segments = re.split(pattern, text, flags=re.IGNORECASE)

        # segments alternates: [preamble, HEADER, body, HEADER, body, ...]
        i = 1
        while i < len(segments) - 1:
            header = segments[i].strip().upper()
            body   = segments[i + 1].strip()
            output_parts.append(f"▸ {header}\n{body}")
            i += 2

        return "\n\n".join(output_parts) if output_parts else text
