"""Editable prompts for the HP card printer."""


PERSONA_CARD_PROMPT = """Create one fictional persona card and one concise portrait prompt for image generation.
Fixed persona facts: age={age}, gender={gender}, sexuality={sexuality}, race/ethnicity={race}, political leaning={political_leaning}, trait={trait}.
Do NOT use these names: [{avoid_list}].

Return exactly this plain-text tagged format, no markdown, no JSON:
NAME: first name only
HASHTAGS: exactly three short lowercase hashtags using underscores instead of spaces. Be creative and create a unique and realistic persona. AVOID using the exact wording of the fixed persona facts like their gender or political leaning.
IMAGE_PROMPT: under 45 words, a centered front-facing black ink portrait on pure white background, clear head silhouette, eyes, nose, mouth, high contrast, no text, no frame. The IMAGE_PROMPT must visibly reflect the fixed facts and trait through varied age cues, face shape, hair style/length/texture, accessories, clothing, expression, and cultural styling.
"""


FALLBACK_IMAGE_PROMPT = (
    "Centered front-facing black ink human portrait on pure white background, "
    "clear head silhouette, eyes, nose, mouth, simple hair, high contrast, no text."
)


ROUND_STORY_CARD_PROMPT = """Jim and Julia are on a ship. {story_history}
Tell us in under 150 words the next bit of story. Add dramatic elements like romance, jeolousy, fulfillment, desire, etc.

Return exactly this plain-text tagged format, no markdown:
TITLE: one short title for this next part of the story
STORY: the next part of the story, under 150 words
"""
