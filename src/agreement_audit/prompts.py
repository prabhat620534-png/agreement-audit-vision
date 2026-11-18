"""
Prompts sent to the vision model. Built dynamically so the model is only asked
for the fields that the free checks could NOT answer (fewer tokens, fewer mistakes).
"""
from .config import SETTINGS

NAME_RULES = """"society_name":
   - Locate the main table at the top. Read the text written inside the cell next to or below "Name of society (customer)" or "Name of society".
   - Extract the COMPLETE name written in that box. It can be a Housing Society, Apartment, Association, OR a Private Limited Construction / Builder company (e.g., "Sunrise Builders Pvt Ltd", "Lakeview Apartment Owners Association", "Green Meadows CHSL").
   - NEVER output "{vendor}" (that is the service vendor) or a person's name.
   - If that customer box is blank or not on this page, use exactly: "Not listed"."""

STAMP_RULES = """"is_stamped": "Yes" if you can see ANY of these anywhere on the page, especially in the bottom signature area: a circular or rectangular rubber ink stamp or seal (purple, blue or black; society seal, company seal, notary seal), a government e-Stamp certificate or stamp paper, a revenue stamp, or an "eSigned using Aadhaar" block. Otherwise "No"."""

SIGN_RULES = """"is_signed": "Yes" if you can see ANY handwritten signature, initials or pen scribble, usually above or beside words like "SECRETARY", "Chairman", "Authorised Signatory", "For ... CHS Ltd", or in a signature box, or an "eSigned using Aadhaar" block. Handwriting used only to FILL IN form fields (a name, designation or phone number written in capital letters inside a table) is NOT a signature. Otherwise "No"."""

HINT_RULES = ('\n   - The name may be HANDWRITTEN. Hint from the file name: "{hint}". The written name is '
              'usually similar but often longer (e.g. it adds "Sahakari Gruhnirman Sanstha", "CHS Ltd", '
              '"Co-op Housing Society"). Copy what is actually written in the box; use the hint only to help '
              'read unclear handwriting.')

BOX_FILLED_RULE = ('\n   - Also answer "name_box_filled": "Yes" if ANYTHING is typed or handwritten in that customer box '
                   '(even if hard to read), "No" if the box is empty.')


def build_prompt(want_name, want_stamp, want_sign, hint="", vendor=None):
    vendor = vendor or SETTINGS.vendor_name
    parts, keys = [], []
    if want_name:
        rules = NAME_RULES.format(vendor=vendor)
        if hint:
            rules += HINT_RULES.format(hint=hint)
        rules += BOX_FILLED_RULE
        parts.append(rules)
        keys += ['"society_name": "..."', '"name_box_filled": "Yes or No"']
    if want_stamp:
        parts.append(STAMP_RULES)
        keys.append('"is_stamped": "Yes or No"')
    if want_sign:
        parts.append(SIGN_RULES)
        keys.append('"is_signed": "Yes or No"')
    numbered = "\n\n".join(f"{i}. {p}" for i, p in enumerate(parts, 1))
    return (f"Inspect this agreement page image carefully.\n\n{numbered}\n\n"
            f"Return strictly one valid JSON object in this exact format (no markdown, no backticks, no extra text):\n"
            "{" + ", ".join(keys) + "}")
