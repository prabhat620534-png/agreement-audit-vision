"""Generates fictional sample agreements in samples/ (no real customer data)."""
import pymupdf

def make(path, society, esign=False, blank=False):
    doc = pymupdf.open()
    p = doc.new_page()
    p.insert_text((72, 60), "SERVICE AGREEMENT", fontsize=16)
    p.insert_text((72, 80), "Between Acme Services Pvt. Ltd. (Vendor) and the Customer below", fontsize=9)
    rows = [("Name of society (customer)", "" if blank else society), ("City", "Bengaluru"),
            ("Products sold", "Visitor management app"), ("Subscription", "12 months")]
    y = 100
    for a, b in rows:
        for x0, x1, t in ((72, 260, a), (260, 520, b)):
            r = pymupdf.Rect(x0, y, x1, y + 24)
            p.draw_rect(r, color=(0, 0, 0), width=0.8)
            if t:
                p.insert_textbox(r + (4, 5, -4, 0), t, fontsize=10)
        y += 24
    p.insert_text((72, 260), "Terms: The vendor will provide the services listed above ...", fontsize=9)
    p.insert_text((72, 720), "For the Customer: ____________________   SECRETARY", fontsize=10)
    if esign:
        p.insert_text((72, 745), "eSigned using Aadhaar by R. Sharma on 01-11-2026", fontsize=8)
    doc.save(path)

make("samples/Green Meadows B wing -1--3f2a9c1e-0b7d-4e55-9a11-2c3d4e5f6a7b.pdf", "Green Meadows CHSL", esign=True)
make("samples/Lakeview Apartments.pdf", "Lakeview Apartment Owners Association")
make("samples/blank_template.pdf", "", blank=True)
print("ok")
