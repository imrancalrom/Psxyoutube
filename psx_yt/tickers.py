"""PSX stock universe: symbols, company names, sectors and the aliases used to spot them in text.

`ambiguous=True` marks symbols that are also everyday English/Urdu words (POWER, LUCK, PPL, GAL...).
Those only match when written as $SYM / #SYM, or through one of their company-name aliases.

Add or override stocks with a CSV file (see load_tickers): symbol,name,sector,aliases(;-separated),ambiguous
"""

import csv
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class Stock:
    symbol: str
    name: str
    sector: str
    aliases: list[str] = field(default_factory=list)
    ambiguous: bool = False


# fmt: off
_STOCKS = [
    # Oil & gas exploration
    ("OGDC", "Oil & Gas Development Company", "Oil & Gas E&P", ["ogdcl", "oil and gas development", "oil & gas development", "او جی ڈی سی"], False),
    ("PPL", "Pakistan Petroleum Ltd", "Oil & Gas E&P", ["pakistan petroleum"], True),
    ("POL", "Pakistan Oilfields Ltd", "Oil & Gas E&P", ["pakistan oilfields", "pakistan oil fields"], True),
    ("MARI", "Mari Energies Ltd", "Oil & Gas E&P", ["mari petroleum", "mari energies", "mari gas"], True),
    # Oil & gas marketing / refineries
    ("PSO", "Pakistan State Oil", "Oil & Gas Marketing", ["pakistan state oil", "پی ایس او"], False),
    ("APL", "Attock Petroleum Ltd", "Oil & Gas Marketing", ["attock petroleum"], False),
    ("SNGP", "Sui Northern Gas Pipelines", "Oil & Gas Marketing", ["sui northern", "sngpl"], False),
    ("SSGC", "Sui Southern Gas Company", "Oil & Gas Marketing", ["sui southern"], False),
    ("HASCOL", "Hascol Petroleum", "Oil & Gas Marketing", ["hascol petroleum"], False),
    ("ATRL", "Attock Refinery Ltd", "Refinery", ["attock refinery"], False),
    ("NRL", "National Refinery Ltd", "Refinery", ["national refinery"], False),
    ("PRL", "Pakistan Refinery Ltd", "Refinery", ["pakistan refinery"], False),
    ("CNERGY", "Cnergyico PK", "Refinery", ["cnergyico", "byco"], False),
    # Power
    ("HUBC", "Hub Power Company", "Power", ["hub power", "hubco", "حب پاور"], False),
    ("KAPCO", "Kot Addu Power Company", "Power", ["kot addu power"], False),
    ("NCPL", "Nishat Chunian Power", "Power", ["nishat chunian power"], False),
    ("NPL", "Nishat Power Ltd", "Power", ["nishat power"], False),
    ("KEL", "K-Electric", "Power", ["k-electric", "k electric", "kelectric"], False),
    # Cement
    ("LUCK", "Lucky Cement", "Cement", ["lucky cement", "لکی سیمنٹ"], True),
    ("DGKC", "D.G. Khan Cement", "Cement", ["dg khan cement", "d.g. khan cement", "d g khan cement"], False),
    ("MLCF", "Maple Leaf Cement", "Cement", ["maple leaf cement", "maple leaf"], False),
    ("DNCC", "Dandot Cement", "Cement", ["dandot cement", "dandot"], False),
    ("FCCL", "Fauji Cement Company", "Cement", ["fauji cement"], False),
    ("CHCC", "Cherat Cement", "Cement", ["cherat cement"], False),
    ("KOHC", "Kohat Cement", "Cement", ["kohat cement"], False),
    ("PIOC", "Pioneer Cement", "Cement", ["pioneer cement"], False),
    ("ACPL", "Attock Cement Pakistan", "Cement", ["attock cement"], False),
    ("POWER", "Power Cement", "Cement", ["power cement"], True),
    # Fertilizer / conglomerates / chemicals
    ("ENGROH", "Engro Holdings", "Conglomerate", ["engro holdings", "engro corp", "engro corporation", "engro", "اینگرو"], False),
    ("EFERT", "Engro Fertilizers", "Fertilizer", ["engro fertilizer", "engro fertilizers", "engro fert"], False),
    ("FFC", "Fauji Fertilizer Company", "Fertilizer", ["fauji fertilizer", "fauji fert"], False),
    ("FATIMA", "Fatima Fertilizer", "Fertilizer", ["fatima fertilizer", "fatima fert"], True),
    ("DAWH", "Dawood Hercules Corporation", "Fertilizer", ["dawood hercules"], False),
    ("EPCL", "Engro Polymer & Chemicals", "Chemicals", ["engro polymer"], False),
    ("LOTCHEM", "Lotte Chemical Pakistan", "Chemicals", ["lotte chemical"], False),
    # Banks
    ("MCB", "MCB Bank", "Banks", ["mcb bank"], False),
    ("UBL", "United Bank Ltd", "Banks", ["united bank"], False),
    ("HBL", "Habib Bank Ltd", "Banks", ["habib bank"], False),
    ("MEBL", "Meezan Bank", "Banks", ["meezan bank", "meezan", "میزان بینک"], False),
    ("BAHL", "Bank AL Habib", "Banks", ["bank al habib", "bank al-habib"], False),
    ("BAFL", "Bank Alfalah", "Banks", ["bank alfalah", "bank al falah"], False),
    ("NBP", "National Bank of Pakistan", "Banks", ["national bank"], False),
    ("ABL", "Allied Bank Ltd", "Banks", ["allied bank"], False),
    ("AKBL", "Askari Bank", "Banks", ["askari bank"], False),
    ("BOP", "Bank of Punjab", "Banks", ["bank of punjab"], False),
    ("FABL", "Faysal Bank", "Banks", ["faysal bank"], False),
    ("HMB", "Habib Metropolitan Bank", "Banks", ["habib metro", "habib metropolitan"], False),
    ("BIPL", "BankIslami Pakistan", "Banks", ["bankislami", "bank islami"], False),
    ("SNBL", "Soneri Bank", "Banks", ["soneri bank"], False),
    ("JSBL", "JS Bank", "Banks", ["js bank"], False),
    # Technology & communication
    ("SYS", "Systems Ltd", "Technology", ["systems limited", "systems ltd", "system limited"], False),
    ("TRG", "TRG Pakistan", "Technology", ["trg pakistan"], False),
    ("AVN", "Avanceon", "Technology", ["avanceon"], False),
    ("NETSOL", "NetSol Technologies", "Technology", ["netsol technologies"], False),
    ("AIRLINK", "Air Link Communication", "Technology", ["air link", "airlink communication"], False),
    ("PTC", "Pakistan Telecommunication Company", "Technology", ["ptcl", "pakistan telecommunication"], False),
    ("WTL", "WorldCall Telecom", "Technology", ["worldcall"], False),
    ("TELE", "Telecard", "Technology", ["telecard"], True),
    ("HUMNL", "Hum Network", "Technology", ["hum network"], False),
    # Engineering / steel
    ("INIL", "International Industries", "Engineering", ["international industries"], False),
    ("ISL", "International Steels", "Engineering", ["international steels", "international steel"], False),
    ("ASTL", "Amreli Steels", "Engineering", ["amreli steel", "amreli steels"], False),
    ("MUGHAL", "Mughal Iron & Steel", "Engineering", ["mughal steel", "mughal iron"], True),
    # Textiles
    ("NML", "Nishat Mills", "Textile", ["nishat mills"], False),
    ("ILP", "Interloop", "Textile", ["interloop"], False),
    ("GATM", "Gul Ahmed Textile", "Textile", ["gul ahmed"], False),
    ("KTML", "Kohinoor Textile Mills", "Textile", ["kohinoor textile"], False),
    # Pharma
    ("SEARL", "The Searle Company", "Pharma", ["searle"], False),
    ("AGP", "AGP Ltd", "Pharma", [], False),
    ("GLAXO", "GlaxoSmithKline Pakistan", "Pharma", ["glaxosmithkline", "gsk pakistan"], False),
    ("ABOT", "Abbott Laboratories Pakistan", "Pharma", ["abbott"], False),
    ("HINOON", "Highnoon Laboratories", "Pharma", ["highnoon"], False),
    # Autos
    ("INDU", "Indus Motor Company", "Automobile", ["indus motor", "indus motors"], False),
    ("HCAR", "Honda Atlas Cars", "Automobile", ["honda atlas"], False),
    ("ATLH", "Atlas Honda Ltd", "Automobile", ["atlas honda"], False),
    ("MTL", "Millat Tractors", "Automobile", ["millat tractors", "millat tractor"], False),
    ("SAZEW", "Sazgar Engineering Works", "Automobile", ["sazgar"], False),
    ("GHNI", "Ghandhara Industries", "Automobile", ["ghandhara industries"], False),
    ("GAL", "Ghandhara Automobiles", "Automobile", ["ghandhara automobiles"], True),
    ("THALL", "Thal Ltd", "Automobile", ["thal limited"], False),
    # Consumer / misc
    ("PAEL", "Pak Elektron", "Cable & Electrical", ["pak elektron", "pak electron"], False),
    ("NESTLE", "Nestle Pakistan", "Food", ["nestle pakistan"], False),
    ("COLG", "Colgate-Palmolive Pakistan", "Personal Care", ["colgate"], False),
    ("UNITY", "Unity Foods", "Food", ["unity foods"], True),
    ("FFL", "Fauji Foods", "Food", ["fauji foods"], False),
    ("PAKT", "Pakistan Tobacco Company", "Tobacco", ["pakistan tobacco"], False),
    ("PKGS", "Packages Ltd", "Paper & Board", ["packages limited", "packages ltd"], False),
    ("CEPB", "Century Paper & Board", "Paper & Board", ["century paper"], False),
    ("TGL", "Tariq Glass", "Glass", ["tariq glass"], False),
    ("GHGL", "Ghani Glass", "Glass", ["ghani glass"], False),
    ("PABC", "Pakistan Aluminium Beverage Cans", "Misc", ["pakistan aluminium beverage"], False),
    ("PIBTL", "Pakistan International Bulk Terminal", "Transport", ["pakistan international bulk"], False),
    ("PNSC", "Pakistan National Shipping Corporation", "Transport", ["pakistan national shipping", "national shipping corporation"], False),
    ("TPLP", "TPL Properties", "Real Estate", ["tpl properties"], False),
    ("TPL", "TPL Corp Ltd", "Investment", ["tpl corp", "tpl corporation"], False),
    ("JSCL", "Jahangir Siddiqui & Co", "Investment", ["jahangir siddiqui"], False),
]

# Words that name a whole sector. Kept specific on purpose: no bare "bank" (State Bank), "banking" (digital
# banking), "real estate" (property as an investment), "power" or "tech".
# Generic "oil & gas" talk on PSX is mostly about the E&P names, so it counts there.
SECTOR_ALIASES = {
    "Banks": ["banks", "banking sector", "banking stocks", "bank stocks", "بینکنگ سیکٹر", "بینکس"],
    "Cement": ["cement", "cement sector", "cements", "سیمنٹ"],
    "Oil & Gas E&P": ["E&P", "E & P", "exploration and production", "exploration & production", "oil & gas",
                      "oil and gas", "oil sector", "آئل اینڈ گیس"],
    "Oil & Gas Marketing": ["OMC", "OMCs", "oil marketing", "oil marketing companies", "gas utilities"],
    "Refinery": ["refinery", "refineries", "refining", "ریفائنری"],
    "Power": ["power sector", "power stocks", "IPP", "IPPs", "power companies"],
    "Fertilizer": ["fertilizer", "fertilizers", "fertiliser", "fertilisers", "urea", "کھاد"],
    "Technology": ["tech sector", "tech stocks", "technology sector", "technology stocks", "IT sector", "IT stocks"],
    "Automobile": ["auto sector", "autos", "auto stocks", "automobile", "automobiles", "car makers", "assemblers"],
    "Pharma": ["pharma", "pharmaceutical", "pharmaceuticals", "فارما"],
    "Textile": ["textile", "textiles", "textile sector", "ٹیکسٹائل"],
    "Food": ["food sector", "food companies", "food stocks", "FMCG"],
    "Engineering": ["steel", "steel sector", "steel stocks", "engineering sector"],
    "Chemicals": ["chemical sector", "chemicals"],
    "Glass": ["glass sector"],
    "Paper & Board": ["paper sector", "packaging sector"],
    "Tobacco": ["tobacco"],
    "Real Estate": ["real estate sector", "real estate stocks", "REIT", "REITs"],
}
# fmt: on


def load_tickers(extra_csv: str | Path | None = None) -> dict[str, Stock]:
    """Built-in universe, optionally extended/overridden by a CSV file."""
    stocks = {s: Stock(s, n, sec, list(a), amb) for s, n, sec, a, amb in _STOCKS}
    if extra_csv and Path(extra_csv).exists():
        with open(extra_csv, newline="", encoding="utf-8") as f:
            for row in csv.DictReader(f):
                sym = row["symbol"].strip().upper()
                if not sym:
                    continue
                aliases = [a.strip() for a in (row.get("aliases") or "").split(";") if a.strip()]
                stocks[sym] = Stock(
                    sym,
                    (row.get("name") or sym).strip(),
                    (row.get("sector") or "Other").strip(),
                    aliases,
                    (row.get("ambiguous") or "").strip().lower() in ("1", "true", "yes"),
                )
    return stocks
