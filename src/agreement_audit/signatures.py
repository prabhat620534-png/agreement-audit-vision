"""Free, deterministic checks for digital signatures - run before paying for a vision call."""
import re

ESIGN_TEXT = re.compile(r"e\s*-?\s*s[i1l]gned\s+us[i1l]ng\s+aa?dh?aa?r", re.I)   # tolerant to OCR noise


def digital_signature(data: bytes, text: str):
    """
    Returns a list of signals found. A PDF's /ByteRange entry only exists once a signature has
    actually been APPLIED - an empty 'sign here' field doesn't create one - so it is a reliable signal.
    """
    found = []
    if re.search(rb"/ByteRange\s*\[\s*\d+\s+\d+\s+\d+\s+\d+\s*\]", data):
        if re.search(rb"(?i)leegality", data):
            found.append("Leegality signature")
        elif re.search(rb"(?i)docusign", data):
            found.append("DocuSign signature")
        else:
            found.append("Digital signature")
    if ESIGN_TEXT.search(text):
        found.append("Aadhaar eSign text")
    if re.search(r"digitally\s+signed\s+by", text, re.I):
        found.append("'Digitally signed by' text")
    return found
