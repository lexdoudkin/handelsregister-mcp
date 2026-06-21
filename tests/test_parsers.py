"""Offline tests for the deterministic parsers.

Fixtures are *synthetic* strings modelled on the real document formats — no real
register data (which contains personal data) is committed to the repo.
"""

from handelsregister_mcp.parsers import (
    _iso_date,
    _money_to_float,
    _strip_trailing_marker,
    company_to_markdown,
    parse_gesellschafterliste,
    parse_register_extract,
    parse_xjustiz_si,
    to_markdown_table,
)

# --------------------------------------------------------------------- helpers


def test_money_to_float():
    assert _money_to_float("1.000,00 EUR") == 1000.0
    assert _money_to_float("25.000,00 €") == 25000.0
    assert _money_to_float("413100000") == 413100000.0
    assert _money_to_float("") is None
    assert _money_to_float("keine Zahl") is None


def test_iso_date():
    assert _iso_date("21.03.1999") == "1999-03-21"
    assert _iso_date("1966-09-04") == "1966-09-04"  # already ISO -> passthrough
    assert _iso_date("Abruf vom 20.06.2026") == "2026-06-20"
    assert _iso_date("") is None


def test_strip_trailing_marker():
    assert _strip_trailing_marker("...Intelligenz 3.") == "...Intelligenz"
    assert _strip_trailing_marker("...vertreten. b)") == "...vertreten."
    # a legal-form suffix must NOT be mistaken for a section marker
    assert _strip_trailing_marker("Art of X UG (haftungsbeschränkt)") == \
        "Art of X UG (haftungsbeschränkt)"


def test_to_markdown_table():
    md = to_markdown_table([{"a": 1, "b": None}, {"a": 2, "b": "x"}], ["a", "b"])
    assert md.splitlines()[0] == "| a | b |"
    assert "| 1 |  |" in md
    assert to_markdown_table([]) == "_(no rows)_"


# ------------------------------------------------------ register extract (AD)

_AD_TEXT = """
- Wiedergabe des aktuellen Registerinhalts -
Abruf vom 01.06.2026, 10:00
Amtsgericht Charlottenburg
Ausdruck - Handelsregister Abteilung B - HRB 999999 B
1. Anzahl der bisherigen Eintragungen
3 Eintragung(en)
2.a) Firma
Test Beispiel GmbH
b) Sitz, Niederlassung, inländische Geschäftsanschrift, empfangsberechtigte Person, Zweignieder-
lassungen
Berlin
Musterstraße 1, 10115 Berlin
c) Gegenstand des Unternehmens
Entwicklung von Software.
3. Grund- oder Stammkapital
25.000,00 EUR
4.a) Allgemeine Vertretungsregelung
Ist ein Geschäftsführer bestellt, so vertritt er die Gesellschaft allein.
b) Vorstand, Leitungsorgan, geschäftsführende Direktoren, persönlich haftende Gesellschafter, Geschäftsführer, Vertretungsberechtigte und besondere Vertretungsbefugnis
Geschäftsführer:
Mustermann, Max, *01.01.1980, Berlin
6.a) Rechtsform, Beginn, Satzung oder Gesellschaftsvertrag
Gesellschaft mit beschränkter Haftung
Gesellschaftsvertrag vom: 01.01.2020
7. Tag der letzten Eintragung
01.06.2026
"""


def test_parse_register_extract():
    c = parse_register_extract(_AD_TEXT)
    assert c["name"] == "Test Beispiel GmbH"
    assert c["register_number"] == "HRB 999999 B"
    assert c["registered_office"] == "Berlin"
    assert c["business_address"] == "Musterstraße 1, 10115 Berlin"
    assert c["capital"] == 25000.0
    assert c["capital_currency"] == "EUR"
    assert c["entries_count"] == 3
    assert c["legal_form"] == "Gesellschaft mit beschränkter Haftung"
    assert c["last_entry_date"] == "2026-06-01"
    assert c.get("articles_of_association_date") == "2020-01-01"
    assert c["purpose"] == "Entwicklung von Software."
    assert c["management"] == [
        {"name": "Mustermann, Max", "date_of_birth": "1980-01-01", "city": "Berlin"}
    ]


def test_company_to_markdown_renders():
    md = company_to_markdown(parse_register_extract(_AD_TEXT))
    assert "Test Beispiel GmbH" in md
    assert "**Management**" in md
    assert "Mustermann, Max" in md


# ------------------------------------------------------------- XJustiz SI XML

_SI_XML = """<?xml version="1.0" encoding="UTF-8"?>
<tns:nachricht.reg.0400003 xmlns:tns="http://www.xjustiz.de">
  <tns:grunddaten><tns:verfahrensdaten><tns:beteiligung>
    <tns:beteiligter>
      <tns:beteiligtennummer>1</tns:beteiligtennummer>
      <tns:auswahl_beteiligter><tns:organisation>
        <tns:bezeichnung><tns:bezeichnung.aktuell>Test Beispiel GmbH</tns:bezeichnung.aktuell></tns:bezeichnung>
        <tns:sitz><tns:ort>Berlin</tns:ort></tns:sitz>
        <tns:registereintragung><tns:registernummer>HRB 999999 B</tns:registernummer></tns:registereintragung>
      </tns:organisation></tns:auswahl_beteiligter>
    </tns:beteiligter>
  </tns:beteiligung></tns:verfahrensdaten></tns:grunddaten>
  <tns:fachdatenRegister><tns:basisdatenRegister>
    <tns:gegenstand>Entwicklung von Software.</tns:gegenstand>
  </tns:basisdatenRegister>
  <tns:auswahl_zusatzangaben><tns:kapitalgesellschaft><tns:kapital><tns:hoehe>
    <tns:zahl>25000</tns:zahl>
    <tns:auswahl_waehrung><tns:waehrung><tns:code>EUR</tns:code></tns:waehrung></tns:auswahl_waehrung>
  </tns:hoehe></tns:kapital></tns:kapitalgesellschaft></tns:auswahl_zusatzangaben>
  </tns:fachdatenRegister>
</tns:nachricht.reg.0400003>
"""


def test_parse_xjustiz_si():
    d = parse_xjustiz_si(_SI_XML)
    assert d["name"] == "Test Beispiel GmbH"
    assert d["register_number"] == "HRB 999999 B"
    assert d["registered_office"] == "Berlin"
    assert d["capital"] == 25000.0
    assert d["capital_currency"] == "EUR"
    assert "Software" in d["purpose"]
    assert any(p["type"] == "organization" and p["name"] == "Test Beispiel GmbH"
               for p in d["parties"])


def test_parse_xjustiz_si_invalid():
    assert "error" in parse_xjustiz_si("<not-xml")


# ------------------------------------------------------- Gesellschafterliste

_GL_TEXT = """
Liste der Gesellschafter der
Test Beispiel GmbH
Amtsgericht Charlottenburg, HRB 999999 B
lfd. Nummer Nennbetrag der Geschäftsanteile prozentualer Anteil Summe der Nennbeträge prozentualer Anteil Veränderung
Muster Holding GmbH
AG Charlottenburg HRB 111111 B
Berlin
1 - 12500 je 1,00 € je 0,004% 12.500,00 € 50%
entstanden durch Teilung
Beispiel Ventures GmbH
AG München HRB 222222
München
12501 - 25000 je 1,00 € je 0,004% 12.500,00 € 50%
Stammkapital: 25.000,00 €
"""


def test_parse_gesellschafterliste():
    res = parse_gesellschafterliste(_GL_TEXT)
    assert res["confidence"] == "high"
    assert res["stammkapital_eur"] == 25000.0
    sh = res["shareholders"]
    assert len(sh) == 2
    assert sh[0]["shareholder"] == "Muster Holding GmbH"
    assert sh[0]["type"] == "company"
    assert sh[0]["register"] == "AG Charlottenburg HRB 111111 B"
    assert sh[0]["city"] == "Berlin"
    assert sh[0]["nominal_total_eur"] == 12500.0
    assert sh[0]["percent"] == "50%"
    assert sh[1]["shareholder"] == "Beispiel Ventures GmbH"
    assert sh[1]["city"] == "München"


def test_parse_gesellschafterliste_garbled_low_confidence():
    # No recognizable table -> low confidence, raw text preserved for the caller.
    res = parse_gesellschafterliste("just some scanned noise with no table at all")
    assert res["confidence"] == "low"
    assert res["raw_text"]
