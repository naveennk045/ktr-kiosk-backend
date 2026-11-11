"""Hard-coded menu content for the TMS board (descriptions, facts, images, categories).

Petpooja only gives us item names and SKUs, so the customer-facing copy lives here until
it moves into the catalog. Lines are matched by normalised ``item_name``. ``image`` is a
key the TMS client resolves to its own static asset (``/img/<key>.jpg``); ``None`` means
the client draws the plaid placeholder.
"""

from __future__ import annotations

import re
from typing import Any

CATEGORIES: dict[str, dict[str, Any]] = {
    "davangere": {
        # Free-text kitchen options the kiosk offers (sent as item options, not priced).
        "options": ["Extra benne", "Extra crispy", "Less spicy", "Chutney on the side"],
        "stage": "On the tawa",
        "name": "Davangere Benne Dose",
        "short": "Davangere",
        "image": "dav",
        "fact": "Benne means butter in Kannada. Davangere, a city in central Karnataka, is famous for this dose.",
    },
    "bengaluru": {
        "options": ["Extra crispy", "Less spicy", "Less oil", "Chutney on the side"],
        "stage": "On the tawa",
        "name": "Bengaluru Dose",
        "short": "Bengaluru",
        "image": "blr",
        "fact": "Pudi is a spiced lentil powder, spread inside the dose before it's folded.",
    },
    "idli": {
        "options": ["Extra chutney", "Extra ghee", "Less spicy"],
        "stage": "Steaming",
        "name": "Idlis",
        "short": "Idlis",
        "image": "thatte",
        "fact": "Idli batter is rice and urad dal, fermented overnight. Thatte means plate.",
    },
    "vada": {
        "options": ["Extra crispy", "Extra chutney"],
        "stage": "Frying",
        "name": "Vadas",
        "short": "Vadas",
        "image": None,
        "fact": "Medu means soft. A good medu wada is crisp outside and soft inside.",
    },
    "rice": {
        "options": ["Less spicy", "Extra ghee"],
        "stage": "In the pot",
        "name": "Rice",
        "short": "Rice",
        "image": None,
        "fact": "In Karnataka, bath is the name for one-pot rice and rava dishes.",
    },
    "dessert": {
        "options": ["Less sweet", "Extra ghee"],
        "stage": "In the pot",
        "name": "Desserts",
        "short": "Desserts",
        "image": None,
        "fact": "Kesari takes its name from kesar, saffron.",
    },
    "addon": {
        "options": [],
        "stage": "Plating",
        "name": "Add-ons",
        "short": "Add-ons",
        "image": None,
        "fact": "Chutneys are ground fresh through the day.",
    },
    "paddu": {
        "options": ["Extra chutney", "Extra ghee", "Less spicy"],
        "stage": "On the paddu pan",
        "name": "Paddu",
        "short": "Paddu",
        "image": None,
        "fact": "Paddu are cooked in a pan with round hollows, from the same fermented batter as dose.",
    },
    "coffee": {
        "options": ["Strong", "Light", "Less sugar", "No sugar"],
        "stage": "Brewing",
        "name": "Coffee",
        "short": "Coffee",
        "image": "coffee",
        "fact": "Filter coffee is poured between the tumbler and the dabara to cool it down and build the froth.",
    },
}


def _item(
    cat: str,
    item_id: str,
    name: str,
    image: str | None,
    short: str,
    lead: str,
    *,
    sig: bool = False,
    trad: bool = False,
    fact: str | None = None,
    aliases: tuple[str, ...] = (),
) -> dict[str, Any]:
    return {
        "id": item_id,
        "category": cat,
        "name": name,
        "image": image,
        "short": short,
        "lead": lead,
        "fact": fact if fact is not None else CATEGORIES[cat]["fact"],
        "signature": sig,
        "traditional": trad,
        "aliases": list(aliases),
    }


# Order matters for duplicate names ("Benne Masala Dose" exists in both dose styles): first wins.
MENU_ITEMS: list[dict[str, Any]] = [
    _item("davangere", "dv-open", "Benne Open Dose", "dav", "Served open, roasted in benne.",
          "The Davangere dose served open-faced, roasted in benne until the edges turn golden.", sig=True, trad=True),
    _item("davangere", "dv-masala", "Benne Masala Dose", "davsada", "With potato palya, roasted in benne.",
          "Soft inside, crisp outside, roasted in benne and filled with potato palya.", sig=True, trad=True),
    _item("davangere", "dv-khali", "Khali Dose", "dav", "The plain Davangere dose.",
          "Khali means plain: the Davangere dose on its own, with chutney.", trad=True, fact="Khali means plain."),
    _item("davangere", "dv-sada", "Benne Sada Dose", "davsada", "Plain dose, roasted in benne.",
          "A plain Davangere dose roasted in benne, served with chutney.", trad=True),
    _item("bengaluru", "bl-bpm", "Benne Pudi Masala Dose", "bennepudi", "Benne, pudi and potato palya.",
          "Crisp Bengaluru dose with benne, spiced pudi and potato palya inside.", sig=True,
          aliases=("Benne Pudi Masala",)),
    _item("bengaluru", "bl-bgr", "Benne Garlic Roast Dose", "blr", "Roasted crisp with benne and garlic.",
          "A Bengaluru dose roasted extra crisp with benne and crushed garlic."),
    _item("bengaluru", "bl-bgrm", "Benne Garlic Roast Masala Dose", "blr", "Benne, garlic and potato palya.",
          "Roasted extra crisp with benne and crushed garlic, filled with potato palya."),
    _item("bengaluru", "bl-bgrp", "Benne Garlic Roast Plain Dose", "blr", "Crisp with benne and garlic.",
          "Roasted extra crisp with benne and crushed garlic, served plain with chutney."),
    _item("bengaluru", "bl-ggr", "Ghee Garlic Roast Dose", "blr", "Roasted crisp with ghee and garlic.",
          "A Bengaluru dose roasted extra crisp with ghee and crushed garlic."),
    _item("bengaluru", "bl-bpp", "Benne Pudi Plain Dose", "blr", "Benne and spiced pudi.",
          "Crisp Bengaluru dose with benne and a layer of spiced pudi."),
    _item("bengaluru", "bl-bm", "Benne Masala Dose", "blr", "Benne and potato palya.",
          "Crisp Bengaluru dose with benne and potato palya."),
    _item("bengaluru", "bl-bp", "Benne Plain Dose", "blr", "Crisp, golden, with benne.",
          "A crisp, golden Bengaluru dose with benne."),
    _item("bengaluru", "bl-gpm", "Ghee Pudi Masala Dose", "blr", "Ghee, pudi and potato palya.",
          "Crisp Bengaluru dose with ghee, spiced pudi and potato palya."),
    _item("bengaluru", "bl-gpp", "Ghee Pudi Plain Dose", "blr", "Ghee and spiced pudi.",
          "Crisp Bengaluru dose with ghee and spiced pudi."),
    _item("bengaluru", "bl-gm", "Ghee Masala Dose", "blr", "Ghee and potato palya.",
          "Crisp Bengaluru dose with ghee and potato palya."),
    _item("bengaluru", "bl-gp", "Ghee Plain Dose", "blr", "Crisp, golden, with ghee.",
          "A crisp, golden Bengaluru dose with ghee."),
    _item("idli", "id-wada", "Idli Wada", "thatte", "Idli with a crisp medu wada.",
          "Soft idli and a crisp medu wada, with chutney. The tiffin-room pair.", trad=True, aliases=("Idli Vada",)),
    _item("idli", "id-benne", "Benne Idli", "benneidli", "Soft idli with benne.",
          "Soft idli with a generous spoon of benne and chutney."),
    _item("idli", "id-bthatte", "Benne Thatte Idli", "thatte", "Plate idli with benne.",
          "Steamed in a plate so it comes out wide and soft, finished with benne.", sig=True, trad=True),
    _item("idli", "id-gpthatte", "Ghee Pudi Thatte Idli", "thatte", "Plate idli, ghee and pudi.",
          "Wide, soft thatte idli with ghee and spiced pudi.", trad=True),
    _item("idli", "id-gpidli", "Ghee Pudi Idli", "gheepudiidli", "Idli with ghee and pudi.",
          "Soft idli tossed in ghee and spiced pudi."),
    _item("idli", "id-thatte", "Thatte Idli", "thatte", "Wide, soft plate idli.",
          "Thatte means plate. Steamed in one, it comes out wide, light and soft.", trad=True),
    _item("idli", "id-chutney", "Idli Chutney", "thatte", "Classic idli with chutney.",
          "Classic soft idli with fresh chutney."),
    _item("vada", "vd-dal", "Dal Vada", None, "Crisp chana dal fritters.",
          "Crunchy fritters of coarsely ground chana dal, onion and curry leaves.", trad=True, aliases=("Dal Wada",)),
    _item("vada", "vd-maddur", "Maddur Wada", "maddur", "Crisp, flat onion vada from Maddur.",
          "A flat, crunchy vada of rice flour, semolina, onion and curry leaves.", trad=True,
          fact="Maddur Wada is named after Maddur, a stop between Bengaluru and Mysuru where it was sold to travellers.",
          aliases=("Maddur Vada",)),
    _item("paddu", "pd-pudi", "Pudi Paddu", None, "Paddu tossed in spiced pudi.",
          "Soft-centred paddu with crisp edges, tossed in spiced lentil pudi."),
    _item("paddu", "pd-ghee", "Ghee Paddu", None, "Paddu finished with ghee.",
          "Soft-centred paddu with crisp edges, finished with a drizzle of ghee."),
    _item("paddu", "pd-plain", "Plain Paddu", None, "Crisp outside, soft inside.",
          "Round paddu from the dose batter, crisp outside and soft inside, with chutney.", trad=True),
    _item("vada", "vd-medu", "Medu Wada", None, "Crisp outside, soft inside.",
          "Golden urad dal rings, crisp outside and soft inside. Made for dunking in chutney.", trad=True,
          aliases=("Medu Vada",)),
    _item("rice", "rc-chowchow", "Chow Chow Bath", None, "Khara bath and kesari bath on one plate.",
          "The Karnataka breakfast plate: spicy khara bath and sweet kesari bath side by side.", sig=True, trad=True),
    _item("rice", "rc-vangi", "Vangi Bath", None, "Spiced brinjal rice.",
          "Rice tossed with brinjal and vangi bath masala.", trad=True),
    _item("rice", "rc-chitranna", "Chitranna", None, "Lemon rice with peanuts.",
          "Bright lemon rice with peanuts, curry leaves and a tempering of mustard.", trad=True),
    _item("rice", "rc-puli", "Temple Puliyogare", "puli", "Temple-style tamarind rice.",
          "Tangy tamarind rice made the temple way.", sig=True, trad=True, aliases=("Puliyogare",)),
    _item("rice", "rc-shavige", "Shavige Bath", None, "Savoury vermicelli.",
          "Savoury vermicelli tempered with mustard and curry leaves."),
    _item("rice", "rc-bisi", "Bisi Bele Bath", None, "Hot lentil rice with vegetables.",
          "Bisi bele means hot lentil: rice, lentils and vegetables cooked together with spice.", trad=True,
          fact="Bisi bele means hot lentil in Kannada."),
    _item("rice", "rc-khara", "Khara Bath", None, "Spicy rava upma.",
          "Spicy, savoury rava with vegetables.", trad=True),
    _item("dessert", "ds-kesari", "Kesari Bath", None, "Sweet rava with ghee.",
          "Sweet, golden rava cooked in ghee. The sweet half of chow chow bath.", trad=True),
    _item("coffee", "cf-hot", "Hot Filter Coffee", "coffee", "Strong decoction, hot frothy milk.",
          "Strong decoction and hot milk, poured high between tumbler and dabara for the froth.", sig=True, trad=True,
          aliases=("Filter Coffee",)),
    _item("coffee", "cf-cold", "Cold Filter Coffee", "coffee", "Our filter coffee, served cold.",
          "Our filter coffee decoction, served cold. Mumbai heat, Karnataka coffee."),
    _item("coffee", "cf-black", "Black Filter Coffee", "coffee", "Strong decoction, no milk.",
          "Our filter coffee decoction served black: strong, bright and bitter-sweet."),
    _item("addon", "ad-water", "Drinking Water", None, "Packaged drinking water.",
          "A bottle of packaged drinking water."),
    _item("addon", "ad-peanut", "Peanut Chutney", None, "Extra bowl of peanut chutney.",
          "An extra bowl of our peanut chutney."),
    _item("addon", "ad-gatti", "Gatti Dose Chutney", None, "Extra bowl of Gatti dose chutney.",
          "An extra bowl of our Gatti dose chutney."),
    _item("addon", "ad-davangere", "Davangere Dose Chutney", None, "Extra bowl of Davangere dose chutney.",
          "An extra bowl of our Davangere dose chutney."),
    _item("addon", "ad-pudi", "Pudi Powder", None, "Spiced lentil powder, on the side.",
          "Spiced lentil pudi powder, served on the side."),
]

# Spotlight copy, read as "Token 42 just ordered the <name>, <pitch>".
PITCHES: dict[str, str] = {
    "dv-open": "the Davangere dose served open-faced, roasted in benne until the edges turn golden.",
    "dv-masala": "the dose Davangere is famous for. Soft inside, crisp outside, roasted in benne and filled with potato palya. If you're still deciding, this is your sign.",
    "dv-khali": "khali means plain: the Davangere dose on its own, with fresh chutney.",
    "dv-sada": "a plain Davangere dose roasted in benne, served with chutney.",
    "bl-bpm": "crisp Bengaluru dose with benne, spiced pudi and potato palya inside. Our most loaded dose.",
    "bl-bpp": "crisp Bengaluru dose with benne and a layer of spiced pudi.",
    "bl-bm": "crisp Bengaluru dose with benne and potato palya.",
    "bl-bp": "a crisp, golden Bengaluru dose with benne.",
    "bl-gpm": "crisp Bengaluru dose with ghee, spiced pudi and potato palya.",
    "bl-gpp": "crisp Bengaluru dose with ghee and spiced pudi.",
    "bl-gm": "crisp Bengaluru dose with ghee and potato palya.",
    "bl-gp": "a crisp, golden Bengaluru dose with ghee.",
    "id-wada": "soft idli and a crisp medu wada, with chutney. The tiffin-room pair.",
    "id-benne": "soft idli with a generous spoon of benne and chutney.",
    "id-bthatte": "steamed in a plate so it comes out wide and soft, then finished with benne.",
    "id-gpthatte": "wide, soft thatte idli with ghee and spiced pudi.",
    "id-gpidli": "soft idli tossed in ghee and spiced pudi.",
    "id-thatte": "thatte means plate. Steamed in one, it comes out wide, light and soft.",
    "id-chutney": "classic soft idli with fresh chutney.",
    "vd-dal": "crunchy fritters of coarsely ground chana dal, onion and curry leaves.",
    "vd-medu": "crisp golden rings that stay soft inside. Dunk one in chutney and chase it with a hot filter coffee.",
    "rc-chowchow": "the Karnataka breakfast plate: spicy khara bath and sweet kesari bath side by side.",
    "rc-vangi": "rice tossed with brinjal and vangi bath masala.",
    "rc-chitranna": "bright lemon rice with peanuts, curry leaves and a mustard tempering.",
    "rc-puli": "tangy tamarind rice made the temple way.",
    "rc-shavige": "savoury vermicelli tempered with mustard and curry leaves.",
    "rc-bisi": "bisi bele means hot lentil: rice, lentils and vegetables cooked together with spice.",
    "rc-khara": "spicy, savoury rava with vegetables.",
    "ds-kesari": "sweet, golden rava cooked in ghee. The sweet half of chow chow bath.",
    "cf-hot": "strong decoction and hot milk, poured high between tumbler and dabara for that froth. A Karnataka morning in a steel cup.",
    "cf-cold": "our filter coffee decoction, served cold. Mumbai heat, Karnataka coffee.",
    "ad-peanut": "an extra bowl of our peanut chutney.",
    "ad-gatti": "an extra bowl of our Gatti dose chutney.",
    "ad-davangere": "an extra bowl of our Davangere dose chutney.",
    "ad-pudi": "spiced lentil pudi powder, on the side.",
}
_THATTE_FACT = "Thatte means plate. The idli steams in a shallow plate, so it comes out wide and soft."
for _m in MENU_ITEMS:
    _m["pitch"] = PITCHES.get(_m["id"], _m["lead"])
    if _m["id"] in ("id-thatte", "id-bthatte", "id-gpthatte"):
        _m["fact"] = _THATTE_FACT
    _m["options"] = list(CATEGORIES[_m["category"]]["options"])
    if _m["id"] == "cf-cold":
        _m["options"] = ["Less sugar", "No sugar", "Less ice"]
    if _m["id"] == "rc-chowchow":
        _m["fact"] = "Chow chow means a mix: khara bath and kesari bath on one plate."

# "Served today" milestones fire every SERVED_STEP units, per dish and per group.
SERVED_STEP = 50
GROUP_BY_CATEGORY: dict[str, str] = {
    "davangere": "dose", "bengaluru": "dose", "idli": "idli", "vada": "vada",
    "rice": "rice", "dessert": "dessert", "coffee": "coffee", "paddu": "paddu",
}
GROUPS: dict[str, dict[str, Any]] = {
    "dose": {"one": "dose", "many": "doses", "image": "dav"},
    "idli": {"one": "idli plate", "many": "idli plates", "image": "thatte"},
    "vada": {"one": "vada plate", "many": "vada plates", "image": None},
    "rice": {"one": "rice dish", "many": "rice dishes", "image": "puli"},
    "dessert": {"one": "Kesari Bath", "many": "Kesari Baths", "image": None},
    "coffee": {"one": "filter coffee", "many": "filter coffees", "image": "coffee"},
    "paddu": {"one": "paddu plate", "many": "paddu plates", "image": None},
}

TICKER: list[dict[str, str]] = [
    {"k": "Benne", "t": "means butter in Kannada. Our Davangere Dose is roasted in it."},
    {"k": "Thatte", "t": "means plate. That's why our thatte idli is wide and flat."},
    {"k": "Medu", "t": "means soft. A good vada is crisp outside, soft inside."},
    {"k": "Bisi bele", "t": "means hot lentil. Bisi Bele Bath is rice, lentils and vegetables in one pot."},
    {"k": "Chow chow", "t": "means a mix: khara bath and kesari bath on one plate."},
    {"k": "Pudi", "t": "is a spiced lentil powder, spread inside the dose before folding."},
    {"k": "Kesari", "t": "takes its name from kesar, saffron."},
    {"k": "Ritual", "t": "Filter coffee is poured between tumbler and dabara to build froth."},
    {"k": "Overnight", "t": "Our idli and dose batter ferments overnight for the tang."},
    {"k": "Plaid", "t": "Our plaid comes from the fabric worn at real Karnataka tiffin counters."},
    {"k": "Served right", "t": "Banana leaf and steel, no plastic in sight."},
    {"k": "Chutney", "t": "Coconut chutney is made fresh, and refills are free. Just ask."},
    {"k": "Tiffin", "t": "In Karnataka, tiffin means a light meal: breakfast or an evening bite."},
]

# Full-screen story reel shown when the board has been idle.
REEL: list[dict[str, Any]] = [
    {"image": "store", "kicker": "Welcome to KTR", "title": "A Bengaluru tiffin room in Versova",
     "body": "Hand-poured filter coffee, benne-roasted dose and plaid everywhere you look."},
    {"image": "dav", "kicker": "Signature", "title": "Davangere Dose",
     "body": "Benne means butter in Kannada. This dose is roasted in it until it turns golden."},
    {"image": "thatte", "kicker": "The traditional one", "title": "Thatte Idli",
     "body": "Thatte means plate. Steamed in one, it comes out wide, light and soft."},
    {"image": "sip", "kicker": "The ritual", "title": "Filter coffee, poured high",
     "body": "Poured between tumbler and dabara to cool it and build the froth."},
    {"image": None, "kicker": "Crunch time", "title": "Vada",
     "body": "Medu means soft. Crisp outside, soft inside, made for dunking in chutney."},
    {"image": "puli", "kicker": "Temple style", "title": "Temple Puliyogare",
     "body": "Tangy tamarind rice, made the way temple kitchens in Karnataka make it."},
    {"image": None, "kicker": "Breakfast, Karnataka style", "title": "Chow Chow Bath",
     "body": "Spicy khara bath and sweet kesari bath, side by side on one plate."},
    {"image": "table", "kicker": "Served right", "title": "Banana leaf and steel",
     "body": "No plastic in sight, just like the tiffin counters of Karnataka."},
    {"image": "blr", "kicker": "Classic", "title": "Bengaluru Dose",
     "body": "Rice and urad dal batter, fermented overnight, for that tang and crisp."},
    {"image": "space", "kicker": "Our look", "title": "Worn in plaid",
     "body": "Our plaid comes from the fabric worn at real Karnataka tiffin counters."},
    {"image": "mascot", "kicker": "Meet our hostess", "title": "The KTR mascot",
     "body": "Built from the same shapes as the KTR wordmark, dressed in our plaid."},
    {"image": "patrike", "kicker": "Read while you wait", "title": "The Patrike zine",
     "body": "House illustrations and the story of the tiffin room, right at your table."},
]


def _normalise(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", name.lower())


_BY_NAME: dict[str, dict[str, Any]] = {}
for _m in MENU_ITEMS:
    for _n in (_m["name"], *_m["aliases"]):
        _BY_NAME.setdefault(_normalise(_n), _m)


def match_menu_item(item_name: str | None) -> dict[str, Any] | None:
    """Exact match on normalised name, then the longest menu name contained in ``item_name``
    (handles Petpooja suffixes like ``"Medu Wada (2 pcs)"``)."""
    if not item_name:
        return None
    key = _normalise(item_name)
    hit = _BY_NAME.get(key)
    if hit:
        return hit
    best: tuple[int, dict[str, Any]] | None = None
    for n, m in _BY_NAME.items():
        if n and n in key and (best is None or len(n) > best[0]):
            best = (len(n), m)
    return best[1] if best else None


def menu_meta_payload() -> dict[str, Any]:
    return {
        "categories": [{"id": k, **v} for k, v in CATEGORIES.items()],
        "items": MENU_ITEMS,
        "groups": GROUPS,
        "served_step": SERVED_STEP,
        "ticker": TICKER,
        "reel": REEL,
    }
