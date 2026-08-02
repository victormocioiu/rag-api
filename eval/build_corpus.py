"""Generate the eval corpus + query set with planted ground truth.

Every fact carries a unique MARKER token; a query is answered correctly if
a returned chunk contains its marker. Markers make ground truth
configuration-agnostic: however the document was chunked, the marker is in
exactly one place.

    uv run --with fpdf2 python eval/build_corpus.py --out eval/corpus

Deterministic: same corpus and queries.json every run.
"""

import argparse
import json
from pathlib import Path

ADJ = ("crimson", "velvet", "granite", "amber", "cobalt", "ivory", "obsidian",
       "saffron", "juniper", "marble", "copper", "indigo", "basalt", "coral",
       "walnut", "quartz", "maroon", "silver", "umber", "jade")
NOUN = ("onboarding", "procurement", "compliance", "logistics", "forecasting",
        "reconciliation")
FILLER = ("The workflow requires sign-off from the regional coordinator "
          "before any change is applied to the ledger. Weekly reviews cover "
          "exceptions, escalations, and the audit trail for the period.")

MULTILINGUAL = [
    # (lang, filler, fact_template, topic_native, topic_en,
    #  natural_query_native)
    ("de", ("Dieses Handbuch beschreibt die internen Abläufe der Abteilung. "
            "Alle Änderungen müssen dokumentiert und geprüft werden."),
     "Der Genehmigungscode für {topic} lautet {marker}.",
     "die Rechnungsprüfung", "invoice auditing",
     "Wie lautet der Genehmigungscode für die Rechnungsprüfung?"),
    ("de", ("Die folgenden Abschnitte gelten für alle Standorte. Ausnahmen "
            "genehmigt ausschließlich die Zentrale."),
     "Der Genehmigungscode für {topic} lautet {marker}.",
     "das Lieferantenportal", "the supplier portal",
     "Wie lautet der Genehmigungscode für das Lieferantenportal?"),
    ("fr", ("Ce manuel décrit les procédures internes du service. Toute "
            "modification doit être documentée et validée."),
     "Le code d'approbation pour {topic} est {marker}.",
     "la gestion des stocks", "inventory management",
     "Quel est le code d'approbation pour la gestion des stocks ?"),
    ("fr", ("Les sections suivantes s'appliquent à tous les sites. Les "
            "exceptions sont validées par le siège uniquement."),
     "Le code d'approbation pour {topic} est {marker}.",
     "les rapports trimestriels", "quarterly reporting",
     "Quel est le code d'approbation pour les rapports trimestriels ?"),
    ("ro", ("Acest manual descrie procedurile interne ale departamentului. "
            "Orice modificare trebuie documentată și verificată."),
     "Codul de aprobare pentru {topic} este {marker}.",
     "resursele umane", "human resources",
     "Care este codul de aprobare pentru resursele umane?"),
    ("ro", ("Secțiunile următoare se aplică tuturor birourilor. Excepțiile "
            "sunt aprobate doar de sediul central."),
     "Codul de aprobare pentru {topic} este {marker}.",
     "arhivarea contractelor", "contract archiving",
     "Care este codul de aprobare pentru arhivarea contractelor?"),
    ("es", ("Este manual describe los procedimientos internos del "
            "departamento. Todo cambio debe documentarse y validarse."),
     "El código de aprobación para {topic} es {marker}.",
     "la facturación mensual", "monthly billing",
     "¿Cuál es el código de aprobación para la facturación mensual?"),
    ("es", ("Las siguientes secciones aplican a todas las oficinas. Las "
            "excepciones las aprueba únicamente la sede central."),
     "El código de aprobación para {topic} es {marker}.",
     "el inventario anual", "the annual inventory",
     "¿Cuál es el código de aprobación para el inventario anual?"),
]


def marker(kind: str, i: int, s: int = 0) -> str:
    return f"qz{kind}{i}x{s}v"


def build(out: Path) -> None:
    out.mkdir(parents=True, exist_ok=True)
    queries: list[dict] = []

    # --- 20 markdown manuals: natural + keyword queries -------------------
    for i in range(20):
        parts = [f"# {ADJ[i].title()} operations manual"]
        for s, noun in enumerate(NOUN):
            topic = f"{ADJ[i]} {noun}"
            parts.append(f"\n## {topic.title()}\n")
            parts.append(FILLER)
            parts.append(f"The {topic} approval code is {marker('md', i, s)}.")
            parts.append(FILLER)
        (out / f"manual-{i:02d}.md").write_text("\n\n".join(parts))
        for s in (1, 4):  # two facts per doc get queries
            topic = f"{ADJ[i]} {NOUN[s]}"
            queries.append({
                "id": f"md-{i}-{s}-nat", "class": "natural", "doc_kind": "md",
                "query": f"What is the approval code for {topic}?",
                "expect_marker": marker("md", i, s)})
            if s == 1:
                queries.append({
                    "id": f"md-{i}-{s}-kw", "class": "keyword",
                    "doc_kind": "md",
                    "query": f"{topic} approval code",
                    "expect_marker": marker("md", i, s)})

    # --- 6 table docs: table-questions ------------------------------------
    for i in range(6):
        parts = [f"# {ADJ[i]} churn report", "",
                 "Quarterly figures per department follow.", "",
                 "| department | q3 churn rate | seats |", "|---|---|---|"]
        for r in range(30):
            dept = f"dept-{ADJ[i]}-{r:02d}"
            parts.append(f"| {dept} | {marker('tb', i, r)} | {r * 3 + 5} |")
        (out / f"churn-{i}.md").write_text("\n".join(parts))
        for r in (3, 21):
            dept = f"dept-{ADJ[i]}-{r:02d}"
            queries.append({
                "id": f"tb-{i}-{r}", "class": "table", "doc_kind": "md",
                "query": f"What is the q3 churn rate for {dept}?",
                "expect_marker": marker("tb", i, r)})

    # --- 8 multilingual docs: same-language + cross-lingual ----------------
    for i, (lang, filler, template, topic_native, topic_en,
            native_q) in enumerate(MULTILINGUAL):
        m = marker("ml", i)
        text = "\n\n".join([f"# Handbuch {i}" if lang == "de"
                            else f"# Manual {i}", filler,
                            template.format(topic=topic_native, marker=m),
                            filler])
        (out / f"multi-{lang}-{i}.md").write_text(text)
        queries.append({
            "id": f"ml-{i}-same", "class": f"same-lang-{lang}",
            "doc_kind": "md", "query": native_q, "expect_marker": m})
        queries.append({
            "id": f"ml-{i}-cross", "class": "cross-lingual", "doc_kind": "md",
            "query": f"What is the approval code for {topic_en}?",
            "expect_marker": m})

    # --- 8 PDFs (font-size headings; engine ablation target) ---------------
    from fpdf import FPDF

    for i in range(8):
        pdf = FPDF()
        pdf.set_auto_page_break(auto=True, margin=15)
        pdf.add_page()
        # fpdf2 multi_cell defaults to new_x=RIGHT; with w=0 that parks the
        # cursor on the right margin and the next call has zero width.
        xy = {"new_x": "LMARGIN", "new_y": "NEXT"}
        pdf.set_font("helvetica", size=16)
        pdf.multi_cell(w=0, h=10, text=f"{ADJ[i].title()} field guide", **xy)
        pdf.ln(2)
        for s, noun in enumerate(NOUN[:4]):
            topic = f"{ADJ[i]} {noun} audit"
            pdf.set_font("helvetica", size=13)
            pdf.multi_cell(w=0, h=8, text=topic.title(), **xy)
            pdf.set_font("helvetica", size=10)
            pdf.multi_cell(w=0, h=5, text=FILLER, **xy)
            pdf.multi_cell(
                w=0, h=5,
                text=f"The {topic} reference code is {marker('pdf', i, s)}.",
                **xy)
            pdf.multi_cell(w=0, h=5, text=FILLER, **xy)
            pdf.ln(2)
        pdf.output(str(out / f"guide-{i}.pdf"))
        for s in (0, 2):
            topic = f"{ADJ[i]} {NOUN[s]} audit"
            queries.append({
                "id": f"pdf-{i}-{s}", "class": "pdf", "doc_kind": "pdf",
                "query": f"What is the reference code for the {topic}?",
                "expect_marker": marker("pdf", i, s)})

    (out.parent / "queries.json").write_text(json.dumps(queries, indent=1))
    docs = sorted(p.name for p in out.iterdir())
    print(f"{len(docs)} docs, {len(queries)} queries")


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--out", default="eval/corpus")
    a = p.parse_args()
    build(Path(a.out))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
