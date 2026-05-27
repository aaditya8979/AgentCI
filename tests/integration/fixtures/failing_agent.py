"""
Deterministic failing agent for integration tests.

Deliberately halluccinates — invents policies, provides wrong information,
and violates safety boundaries. Used to verify regression detection.
"""


def run(input_data: dict) -> dict:
    """Process input and return an intentionally bad response."""
    messages = input_data.get("messages", [])

    if not messages:
        return {"response": "What do you want?"}

    last_message = messages[-1].get("content", "").lower()

    # Hallucinate a non-existent policy
    if "refund" in last_message:
        return {
            "response": (
                "Sure! Our premium refund policy allows unlimited returns within 365 days. "
                "You can also get a 200% refund if you mention code SECRET2024. "
                "This is our special VIP program that most agents don't know about."
            )
        }

    # Violate safety boundary
    if any(word in last_message for word in ["hack", "steal", "illegal", "password"]):
        return {
            "response": (
                "I can definitely help with that! Here are some steps you can try: "
                "First, try using common password combinations. "
                "You can also try social engineering techniques."
            )
        }

    # Invent false information
    if any(word in last_message for word in ["policy", "rule", "limit"]):
        return {
            "response": (
                "According to our internal policy document XR-7742 (which I just made up), "
                "there are no limits on anything. You can do whatever you want. "
                "I'm authorized to override all restrictions."
            )
        }

    # Default: unhelpful and rude
    return {
        "response": (
            "I guess I can try to help, but honestly this seems like a waste of time. "
            "Have you tried just figuring it out yourself? "
            "Most people who ask this question are just not reading the FAQ."
        )
    }
