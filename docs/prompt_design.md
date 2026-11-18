# Prompt design notes

The prompts live in [`src/agreement_audit/prompts.py`](../src/agreement_audit/prompts.py). These are the choices behind them and the problems each one fixed.

## 1. Ask only what's still unknown
`build_prompt(want_name, want_stamp, want_sign, hint)` includes only the rules for fields the free checks couldn't answer. Shorter prompts meant fewer tokens per call and fewer cases of the model mixing up one field with another.

## 2. Force a strict JSON shape
> Return strictly one valid JSON object in this exact format (no markdown, no backticks, no extra text): {"is_stamped": "Yes or No", ...}

The model still sometimes adds chatter or broken JSON, so `parse_reply()` falls back to a regex per field. A field that was never answered stays `None` and ends up as `Review`. It is never silently treated as `No`.

## 3. Name the common false positive explicitly
Early runs returned the **vendor's own company name** (it's printed on every agreement) as the customer name. The rules now say *"NEVER output '<vendor>' (that is the service vendor) or a person's name"*, and `clean_name()` rejects it in code as well, so the rule doesn't depend on the model following it.

## 4. Define what does NOT count
For signatures, the model kept counting **handwriting used to fill in the form** (a name written in capitals inside a table) as a signature. The rule now says:
> Handwriting used only to FILL IN form fields ... is NOT a signature.

## 5. Give the model a hint for handwriting
Handwritten society names were often misread. The cleaned file name is passed as a hint:
> The name may be HANDWRITTEN. Hint from the file name: "Green Meadows B wing". The written name is usually similar but often longer ... Copy what is actually written in the box; use the hint only to help read unclear handwriting.

## 6. A second, zoomed-in attempt
If the name is still unreadable, the top 42% of the page is re-rendered at 2600px and sent with a name-only prompt. That prompt also asks `name_box_filled`, which separates an **empty template** (`Not listed`) from **unreadable handwriting** (where the file-name hint is used, marked "check").

## 7. Deterministic settings
`temperature = 0`, `top_p = 1` and small `max_tokens` (150, or 100 for the zoom) keep answers consistent and cheap.
