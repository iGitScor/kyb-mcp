"""Typed views over the registry API payloads.

The upstream JSON is wide (50+ fields per company). These models keep the fields a KYB
analyst actually reads and drop the rest, which also keeps tool results small for the model.
Personal data policy: we keep directors' names and roles (public registry data) but never
carry birth dates, which the API also returns.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field

LEGAL_STATUS = {"A": "active", "C": "ceased"}


class _Lenient(BaseModel):
    """Ignore unknown upstream fields so API additions never break the server."""

    model_config = ConfigDict(extra="ignore")


class Director(_Lenient):
    """A natural or legal person listed as a director (dirigeant)."""

    name: str = Field(description="Family name, or company name for a legal person")
    first_names: str | None = Field(default=None, description="Given names (natural persons only)")
    role: str | None = Field(default=None, description="Role as declared, e.g. 'Président de SAS'")
    kind: str | None = Field(default=None, description="'personne physique' or 'personne morale'")
    siren: str | None = Field(default=None, description="SIREN when the director is a company")

    @classmethod
    def from_api(cls, raw: dict[str, Any]) -> Director:
        if raw.get("type_dirigeant") == "personne morale":
            return cls(
                name=raw.get("denomination") or raw.get("nom") or "?",
                role=raw.get("qualite"),
                kind="personne morale",
                siren=raw.get("siren"),
            )
        return cls(
            name=raw.get("nom") or "?",
            first_names=raw.get("prenoms"),
            role=raw.get("qualite"),
            kind=raw.get("type_dirigeant") or "personne physique",
        )


class FinancialYear(_Lenient):
    """Published annual accounts for one fiscal year."""

    year: str
    revenue: int | None = Field(default=None, description="Chiffre d'affaires, in euros")
    net_income: int | None = Field(default=None, description="Résultat net, in euros")


class CompanySummary(_Lenient):
    """One search hit: enough to recognise the company and decide whether to open it."""

    siren: str = Field(description="9-digit legal unit identifier")
    name: str = Field(description="Registered name (nom_complet)")
    status: str = Field(description="'active' or 'ceased' (etat_administratif)")
    legal_form_code: str | None = Field(
        default=None, description="INSEE nature_juridique code, e.g. 5710 = SAS"
    )
    naf_code: str | None = Field(default=None, description="Main activity code (NAF/APE), e.g. 62.01Z")
    category: str | None = Field(default=None, description="PME / ETI / GE")
    created_on: str | None = Field(default=None, description="Creation date, YYYY-MM-DD")
    headcount_band: str | None = Field(default=None, description="INSEE tranche_effectif_salarie code")
    hq_siret: str | None = None
    hq_address: str | None = None
    hq_postal_code: str | None = None
    hq_city: str | None = None
    establishments_open: int | None = Field(default=None, description="Number of open establishments")

    @classmethod
    def from_api(cls, raw: dict[str, Any]) -> CompanySummary:
        hq = raw.get("siege") or {}
        return cls(
            siren=raw["siren"],
            name=raw.get("nom_complet") or raw.get("nom_raison_sociale") or "?",
            status=LEGAL_STATUS.get(raw.get("etat_administratif") or "", "unknown"),
            legal_form_code=raw.get("nature_juridique"),
            naf_code=raw.get("activite_principale"),
            category=raw.get("categorie_entreprise"),
            created_on=raw.get("date_creation"),
            headcount_band=raw.get("tranche_effectif_salarie"),
            hq_siret=hq.get("siret"),
            hq_address=hq.get("adresse"),
            hq_postal_code=hq.get("code_postal"),
            hq_city=hq.get("libelle_commune"),
            establishments_open=raw.get("nombre_etablissements_ouverts"),
        )


class Company(CompanySummary):
    """Full company record used for a KYB review."""

    directors: list[Director] = Field(default_factory=list)
    financials: list[FinancialYear] = Field(default_factory=list, description="Most recent year first")
    last_updated: str | None = Field(default=None, description="Registry last update timestamp")

    @classmethod
    def from_api(cls, raw: dict[str, Any]) -> Company:
        base = CompanySummary.from_api(raw)
        finances_raw = raw.get("finances") or {}
        financials = sorted(
            (
                FinancialYear(year=str(year), revenue=vals.get("ca"), net_income=vals.get("resultat_net"))
                for year, vals in finances_raw.items()
                if isinstance(vals, dict)
            ),
            key=lambda fy: fy.year,
            reverse=True,
        )
        return cls(
            **base.model_dump(),
            directors=[Director.from_api(d) for d in raw.get("dirigeants") or []],
            financials=financials,
            last_updated=raw.get("date_mise_a_jour"),
        )


class SearchResult(BaseModel):
    """A page of search hits."""

    total: int = Field(description="Total matching companies across all pages")
    page: int
    per_page: int
    total_pages: int
    results: list[CompanySummary]
