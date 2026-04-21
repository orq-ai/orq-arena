"""Judge prompt template — lifted verbatim from orq-battlebench/judge.py."""

from __future__ import annotations


def build_judge_prompt(user_query: str, response_a: str, response_b: str) -> str:
    """Assemble the A/B comparison prompt for a judge call."""
    return (
        "[User Question]\n"
        f"{user_query}\n\n"
        "[Response A]\n"
        f"{response_a}\n\n"
        "[Response B]\n"
        f"{response_b}\n\n"
        "Evaluate both responses based on:\n"
        "1. Accuracy and correctness\n"
        "2. Helpfulness and completeness\n"
        "3. Clarity and organization\n"
        "4. Relevance to the question\n\n"
        "Which response is better?\n\n"
        "Your choice:"
    )
