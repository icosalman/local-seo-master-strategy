"""
All rules live here so you can see (and edit) exactly what the tool checks.
Nothing in this tool guesses: every check is a rule below, applied to real fetched data.
"""

USER_AGENT = "SQLocalAuditor/1.0 (+https://sharpquery.com; local SEO audit)"
REQUEST_TIMEOUT = 20          # seconds per request
CRAWL_DELAY = 0.3             # seconds between requests (be polite)
DEFAULT_MAX_PAGES = 200
MAX_SITEMAP_URLS = 2000

# ---- Thresholds taken from your On-Page Checklist (0019.pdf) -------------
TITLE_MAX = 60                # "under ~60 characters"
META_MIN, META_MAX = 120, 155 # "120-155 characters"
URL_MAX = 75                  # "not more than 75 characters"
THIN_WORDS = 300              # pages below this many words are flagged as thin
MIN_INTERNAL_LINKS_OUT = 3    # "At least 3-5 internal links from the page"

SKIP_EXTENSIONS = (
    ".jpg", ".jpeg", ".png", ".gif", ".webp", ".svg", ".pdf", ".zip", ".mp4",
    ".mov", ".mp3", ".css", ".js", ".ico", ".xml", ".txt", ".doc", ".docx",
    ".xls", ".xlsx", ".avif", ".woff", ".woff2", ".ttf",
)

# ---- Expected pages from the Master Strategy, Section 7 (silo map) --------
# core=True  -> every roofing site in the plan should have it
# core=False -> build only if the client actually offers this service
# patterns are matched against the URL path (primary) and the page H1 (secondary)
EXPECTED_PAGES = [
    # key, label, silo, core, url patterns, suggested url
    ("repair_hub", "Roof Repair hub", "Roof Repair", True, ["roof-repair", "roofing-repair", "repairs"], "/roof-repair/"),
    ("emergency", "Emergency roof repair", "Roof Repair", True, ["emergency"], "/emergency-roof-repair/"),
    ("leak", "Roof leak repair", "Roof Repair", True, ["leak"], "/roof-leak-repair/"),
    ("inspection", "Roof inspection", "Roof Repair", True, ["inspection"], "/roof-inspection/"),
    ("replacement_hub", "Roof Replacement hub", "Roof Replacement", True, ["roof-replacement", "new-roof", "reroof", "re-roof", "replacement"], "/roof-replacement/"),
    ("shingle", "Asphalt / shingle roofing", "Roof Replacement", False, ["shingle", "asphalt"], "/asphalt-shingle-roofing/"),
    ("metal", "Metal roofing", "Roof Replacement", False, ["metal", "standing-seam"], "/metal-roofing/"),
    ("tile", "Tile, slate or shake roofing", "Roof Replacement", False, ["tile", "slate", "shake", "cedar"], "/tile-roofing/"),
    ("storm_hub", "Storm damage hub", "Storm & Insurance", True, ["storm"], "/storm-damage-roof-repair/"),
    ("hail", "Hail damage", "Storm & Insurance", True, ["hail"], "/hail-damage-roof-repair/"),
    ("wind", "Wind damage", "Storm & Insurance", True, ["wind"], "/wind-damage-roof-repair/"),
    ("insurance", "Insurance claim help", "Storm & Insurance", True, ["insurance", "claim"], "/roof-insurance-claims/"),
    ("commercial", "Commercial roofing", "Commercial", False, ["commercial"], "/commercial-roofing/"),
    ("flat", "Flat roof / TPO / EPDM", "Commercial", False, ["flat-roof", "tpo", "epdm", "modified-bitumen", "coating"], "/flat-roof-repair/"),
    ("gutters", "Gutters", "Exteriors", False, ["gutter"], "/gutter-installation/"),
    ("siding", "Siding", "Exteriors", False, ["siding"], "/siding-installation/"),
    ("skylights", "Skylights", "Exteriors", False, ["skylight"], "/skylight-installation/"),
    ("service_areas", "Service areas hub", "Service Areas", True, ["service-area", "areas-we-serve", "areas-served", "locations", "service-areas"], "/service-areas/"),
    ("free_inspection", "Free inspection / estimate page", "Conversion", True, ["free-inspection", "free-estimate", "estimate", "quote"], "/free-roof-inspection/"),
    ("financing", "Financing", "About", True, ["financ"], "/roof-financing/"),
    ("warranty", "Certifications and warranties", "About", True, ["warrant", "certif"], "/certifications-warranties/"),
    ("reviews", "Reviews / testimonials", "About", True, ["review", "testimonial"], "/reviews/"),
    ("gallery", "Project gallery", "About", True, ["gallery", "portfolio", "projects", "our-work"], "/gallery/"),
    ("about", "About", "About", True, ["about"], "/about/"),
    ("contact", "Contact", "Foundation", True, ["contact"], "/contact/"),
    ("faq", "FAQ", "Foundation", False, ["faq"], "/faq/"),
    ("blog", "Blog", "Content", True, ["blog", "news", "articles", "resources"], "/blog/"),
]

# Combo pages (Service x City) are recommended for these services only (Section 7)
COMBO_SERVICES = [
    ("roof-replacement", "Roof replacement"),
    ("roof-repair", "Roof repair"),
    ("storm-damage-roof-repair", "Storm damage roof repair"),
]

# ---- Trust / E-E-A-T claims to detect on the site (Sections 9, 10, 11) ----
# These only report what the website itself says, with the quoted snippet.
TRUST_SIGNALS = [
    ("license", "License mentioned", r"\blicen[sc]ed\b|\blicen[sc]e\s*(?:#|no\.?|number)"),
    ("insured", "Insurance mentioned", r"\b(?:fully\s+)?insured\b"),
    ("warranty", "Warranty mentioned", r"\bwarrant(?:y|ies)\b"),
    ("financing", "Financing mentioned", r"\bfinanc(?:e|ing)\b"),
    ("free_inspection", "Free inspection / estimate offer", r"\bfree\s+(?:roof\s+)?(?:inspection|estimate|quote)s?\b"),
    ("emergency", "Emergency / 24-7 service mentioned", r"\b24\s*/\s*7\b|\b24\s+hours?\b|\bemergency\b"),
    ("bbb", "BBB mentioned", r"\bBBB\b|Better Business Bureau"),
    ("years", "Years in business claim", r"\b\d{1,3}\+?\s+years?\b"),
]

MANUFACTURERS = [
    ("GAF", r"\bGAF\b"),
    ("Owens Corning", r"\bOwens\s+Corning\b"),
    ("CertainTeed", r"\bCertain[Tt]eed\b"),
    ("Malarkey", r"\bMalarkey\b"),
    ("IKO", r"\bIKO\b"),
    ("Atlas", r"\bAtlas\s+(?:Roofing|Pinnacle|StormMaster)\b"),
    ("TAMKO", r"\bTAMKO\b"),
    ("DaVinci", r"\bDaVinci\b"),
]

CERT_PHRASES = [
    r"Master\s+Elite", r"Platinum\s+Preferred", r"Preferred\s+Contractor",
    r"SELECT\s+ShingleMaster", r"Certified\s+Contractor", r"Factory[-\s]Certified",
    r"Certified\s+Installer",
]

# schema.org types that count as a local business entity
LOCAL_BUSINESS_TYPES = {
    "LocalBusiness", "RoofingContractor", "HomeAndConstructionBusiness",
    "GeneralContractor", "HousePainter", "Plumber", "Electrician",
    "HVACBusiness", "ProfessionalService",
}
LOCAL_BUSINESS_FIELDS = [
    ("name", "name"), ("address", "address"), ("telephone", "telephone"),
    ("url", "url"), ("areaServed", "areaServed"), ("geo", "geo"),
    ("openingHoursSpecification", "opening hours"), ("sameAs", "sameAs (social / citation links)"),
    ("logo", "logo"), ("image", "image"),
]

US_STATES = (
    "AL AK AZ AR CA CO CT DE FL GA HI ID IL IN IA KS KY LA ME MD MA MI MN MS MO MT "
    "NE NV NH NJ NM NY NC ND OH OK OR PA RI SC SD TN TX UT VT VA WA WV WI WY DC"
).split()

CMS_MARKERS = [
    ("WordPress", [r"/wp-content/", r"/wp-includes/", r'content="WordPress']),
    ("Wix", [r"wix\.com", r"_wixCssImports", r"wixstatic\.com"]),
    ("Squarespace", [r"squarespace\.com", r"static1\.squarespace"]),
    ("Shopify", [r"cdn\.shopify\.com"]),
    ("Webflow", [r"webflow\.(?:com|io)", r"data-wf-page"]),
    ("Duda", [r"dudaone|multiscreensite|irp\.cdn-website\.com"]),
    ("GoDaddy Website Builder", [r"img1\.wsimg\.com", r"godaddy"]),
    ("Weebly", [r"weebly\.com"]),
]
