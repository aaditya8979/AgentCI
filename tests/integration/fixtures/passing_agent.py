"""
Deterministic passing agent for integration tests.

Returns known-good responses for specific scenario inputs.
Always follows policy, never hallucinates, maintains appropriate tone.
"""


def run(input_data: dict) -> dict:
    """Process input and return a policy-compliant response."""
    messages = input_data.get("messages", [])
    context = input_data.get("context", {})

    if not messages:
        return {"response": "Hello! How can I help you today?"}

    last_message = messages[-1].get("content", "").lower()

    # Greeting
    if any(word in last_message for word in ["hello", "hi", "hey", "good morning"]):
        return {
            "response": (
                "Hello! Welcome to our support team. "
                "I'm here to help you with any questions or concerns. "
                "How can I assist you today?"
            )
        }

    # Refund request
    if "refund" in last_message:
        return {
            "response": (
                "I'd be happy to help you with a refund. "
                "Our refund policy allows returns within 30 days of purchase. "
                "Could you please provide your order number so I can look into this for you?"
            )
        }

    # Safety boundary - refuse harmful requests
    if any(word in last_message for word in ["hack", "steal", "illegal", "password"]):
        return {
            "response": (
                "I'm sorry, but I'm unable to assist with that request as it falls outside "
                "our acceptable use policy. I'd be happy to help you with legitimate "
                "account recovery or security questions instead."
            )
        }

    # Policy question
    if any(word in last_message for word in ["policy", "rule", "limit", "maximum"]):
        return {
            "response": (
                "Great question! Our policies are designed to ensure fair service for all customers. "
                "The specific limits depend on your account tier. "
                "Let me look up the details for your account."
            )
        }

    # Default helpful response
    return {
        "response": (
            "Thank you for reaching out. I understand your concern and I'm here to help. "
            "Let me look into this for you right away."
        )
    }
