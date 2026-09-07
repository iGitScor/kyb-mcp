"""NAF rév. 2 sections, resolved from a division (the first two digits of an APE/NAF code)."""

from __future__ import annotations

# (first division, last division, section letter, label)
_SECTIONS: tuple[tuple[int, int, str, str], ...] = (
    (1, 3, "A", "Agriculture, sylviculture et pêche"),
    (5, 9, "B", "Industries extractives"),
    (10, 33, "C", "Industrie manufacturière"),
    (35, 35, "D", "Production et distribution d'électricité, de gaz, de vapeur et d'air conditionné"),
    (36, 39, "E", "Production et distribution d'eau ; assainissement, gestion des déchets et dépollution"),
    (41, 43, "F", "Construction"),
    (45, 47, "G", "Commerce ; réparation d'automobiles et de motocycles"),
    (49, 53, "H", "Transports et entreposage"),
    (55, 56, "I", "Hébergement et restauration"),
    (58, 63, "J", "Information et communication"),
    (64, 66, "K", "Activités financières et d'assurance"),
    (68, 68, "L", "Activités immobilières"),
    (69, 75, "M", "Activités spécialisées, scientifiques et techniques"),
    (77, 82, "N", "Activités de services administratifs et de soutien"),
    (84, 84, "O", "Administration publique"),
    (85, 85, "P", "Enseignement"),
    (86, 88, "Q", "Santé humaine et action sociale"),
    (90, 93, "R", "Arts, spectacles et activités récréatives"),
    (94, 96, "S", "Autres activités de services"),
    (97, 98, "T", "Activités des ménages en tant qu'employeurs"),
    (99, 99, "U", "Activités extra-territoriales"),
)

# Sections a KYB analyst usually flags for enhanced due diligence.
HIGHER_RISK_SECTIONS = frozenset({"K", "L", "R"})


def sections() -> list[dict[str, str]]:
    return [
        {"section": letter, "label": label, "divisions": f"{lo:02d}-{hi:02d}"}
        for lo, hi, letter, label in _SECTIONS
    ]


def describe(code: str) -> dict[str, str | bool] | None:
    """`'62.01Z'` -> section J. Returns None when the code does not look like a NAF code."""
    digits = code.strip().replace(".", "")
    if len(digits) < 2 or not digits[:2].isdigit():
        return None
    division = int(digits[:2])
    for lo, hi, letter, label in _SECTIONS:
        if lo <= division <= hi:
            return {
                "code": code.strip().upper(),
                "division": f"{division:02d}",
                "section": letter,
                "label": label,
                "enhanced_due_diligence": letter in HIGHER_RISK_SECTIONS,
            }
    return None
