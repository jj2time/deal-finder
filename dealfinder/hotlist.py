"""The hot list: areas with something going on — Article 4 directions coming in, big projects,
regeneration. Kept by hand (by you, or updated in a Claude session), because upcoming changes appear in
council papers and news, not in any data feed.

Each entry names the councils it applies to (as postcodes.io names them), so a search in an area that
falls in one of those councils shows a heads-up. Summaries are short and in our own words; follow the
source links and check with the council before relying on a date.
"""
from __future__ import annotations

import json
import secrets
from datetime import date
from typing import Any

CATEGORIES = ["Article 4 coming", "Article 4 in force", "Major project", "Regeneration", "Other"]
STAGES = ["In force", "Expansion", "Coming", "Proposed", "Project underway"]

# Stage, exact areas covered, and the page that explains each starting entry. Filled into entries saved
# before these fields existed (matched by title), and used when the person hasn't set their own.
SEED_EXTRA = {
    "Liverpool: HMO Article 4 in force since June 2021 (11 wards incl. Wavertree)": {
        "stage": "In force",
        "where": ("Former wards of Anfield, Central, Greenbank, Kensington and Fairfield, Picton, Princes Park, "
                  "Riverside, Tuebrook and Stoneycroft, and Wavertree, plus parts of Church and Kirkdale "
                  "(and the Dales area of Greenbank since 2018)"),
        "link": "https://liverpool.gov.uk/planning-and-building-control/planning-permission/planning-permission-for-hmos/",
    },
    "Liverpool: HMO Article 4 expansion (Oct 2026) and citywide plan (2027)": {
        "stage": "Expansion",
        "where": ("Now (if upheld): Kirkdale, Everton, County, Walton, Orrell Park, part of Fazakerley, part of "
                  "Tuebrook Larkhill, Old Swan, part of Stoneycroft, Penny Lane, part of Calderstones, and "
                  "St Michaels and Sefton Park. From about Oct 2027: the rest of Liverpool"),
        "link": "https://www.birkenhead.news/liverpool-council-to-strengthen-hmo-powers/",
    },
    "Preston: HMO Article 4": {
        "stage": "Coming",
        "where": "Preston (the council's map shows the exact streets covered)",
        "link": "https://www.preston.gov.uk/article/12132/Article-4-Direction-on-HMOs",
    },
    "Hertsmere (Potters Bar): HMO Article 4": {
        "stage": "Coming",
        "where": "Potters Bar",
        "link": "https://www.hertsmere.gov.uk/news/residents-invited-to-comment-on-proposed-article-4-direction-in-relation-to-hmos-in-potters-bar",
    },
    "North Tyneside: HMO Article 4 in eight wards": {
        "stage": "Coming",
        "where": "Eight North Tyneside wards (ward names in the linked article)",
        "link": "https://www.planninggeek.co.uk/2026/north-tyneside-hmo-article-4/",
    },
    "Burnley: HMO Article 4 extending to six more wards": {
        "stage": "Expansion",
        "where": "Six more Burnley wards on top of those already covered (ward names in the linked article)",
        "link": "https://www.planninggeek.co.uk/2026/burnley-hmo-article-4-made/",
    },
    "Bury: borough-wide HMO Article 4": {
        "stage": "In force",
        "where": "The whole of Bury borough",
        "link": "https://www.bury.gov.uk/planning-building-control/planning-permission/article-4-directions",
    },
    "Sizewell C nuclear power station (Suffolk)": {
        "stage": "Project underway",
        "where": "Sizewell, near Leiston (IP16); knock-on demand in Saxmundham (IP17) and Ipswich",
        "link": "https://www.newcivilengineer.com/latest/sizewell-c-has-awarded-almost-1bn-in-local-contracts-at-two-year-mark-of-construction-16-01-2026/",
    },
}


def default_stage(category: str) -> str:
    return {"Article 4 in force": "In force", "Article 4 coming": "Coming",
            "Major project": "Project underway"}.get(category, "")

SEED_VERSION = 3
# Seed entries replaced in later versions (removed only if the person never edited them).
REPLACED_SEEDS = {2: ["Liverpool: HMO Article 4 spreading across the city"],
                  3: ["Liverpool: HMO Article 4 spreading across the city", "Liverpool: HMO Article 4 in force since June 2021 (11 wards incl. Wavertree)", "Liverpool: HMO Article 4 expansion (Oct 2026) and citywide plan (2027)", "Preston: HMO Article 4", "Hertsmere (Potters Bar): HMO Article 4", "North Tyneside: HMO Article 4 in eight wards", "Burnley: HMO Article 4 extending to six more wards", "Bury: borough-wide HMO Article 4", "Sizewell C nuclear power station (Suffolk)"]}
# Researched 11-12 Nov 2026: upcoming HMO Article 4 directions (2027-2028) and major projects.
SEED: list[dict[str, Any]] = [
 {
  "title": "Bristol: HMO Article 4 extending to six more areas",
  "category": "Article 4 coming",
  "stage": "Expansion",
  "councils": [
   "Bristol, City of"
  ],
  "postcodes": [
   "BS4",
   "BS5",
   "BS7",
   "BS10",
   "BS16"
  ],
  "status": "Reported to take effect 1 Jan 2027",
  "key_date": "2027-01-01",
  "where": "Brislington, Frome Vale, Purdown, Southmead and Horfield, St George, Westbury Park",
  "summary": "Bristol is adding six more areas to its existing small-HMO controls.",
  "impact": "New small HMOs in these areas will need planning permission from the start date.",
  "sources": [
   {
    "title": "PlanWatch: Article 4 HMO directions by council",
    "url": "https://planwatch.co.uk/guides/article-4-hmo-directions-by-council"
   },
   {
    "title": "Planning Geek: Article 4 HMO map",
    "url": "https://www.planninggeek.co.uk/gpdo/article-4/hmos/"
   }
  ],
  "link": "https://planwatch.co.uk/guides/article-4-hmo-directions-by-council",
  "checked": "2026-11-12"
 },
 {
  "title": "Preston: HMO Article 4",
  "category": "Article 4 coming",
  "stage": "Coming",
  "councils": [
   "Preston"
  ],
  "postcodes": [
   "PR1",
   "PR2"
  ],
  "status": "Made 29 Jan 2026; takes effect 15 Feb 2027 if the council confirms it",
  "key_date": "2027-02-15",
  "where": "The areas on the council's map",
  "summary": "A non-immediate direction; it only starts if the council confirms it.",
  "impact": "New small HMOs in the covered area would need planning permission from 15 Feb 2027.",
  "sources": [
   {
    "title": "Preston City Council: Article 4 Direction on HMOs",
    "url": "https://www.preston.gov.uk/article/12132/Article-4-Direction-on-HMOs"
   }
  ],
  "link": "https://www.preston.gov.uk/article/12132/Article-4-Direction-on-HMOs",
  "checked": "2026-11-12"
 },
 {
  "title": "Wyre Forest (Kidderminster): HMO Article 4",
  "category": "Article 4 coming",
  "stage": "Coming",
  "councils": [
   "Wyre Forest"
  ],
  "postcodes": [
   "DY10",
   "DY11"
  ],
  "status": "Reported to take effect around 20 Feb 2027",
  "key_date": "2027-02-20",
  "where": "Kidderminster",
  "summary": "Wyre Forest consulted on removing the right to convert homes to small HMOs in Kidderminster.",
  "impact": "New small HMOs in Kidderminster would need planning permission.",
  "sources": [
   {
    "title": "Article 4 Checker: Wyre Forest",
    "url": "https://article4checker.com/article-4/wyre-forest-district-council/"
   },
   {
    "title": "PlanWatch",
    "url": "https://planwatch.co.uk/guides/article-4-hmo-directions-by-council"
   }
  ],
  "link": "https://article4checker.com/article-4/wyre-forest-district-council/",
  "checked": "2026-11-12"
 },
 {
  "title": "Telford and Wrekin: HMO Article 4",
  "category": "Article 4 coming",
  "stage": "Coming",
  "councils": [
   "Telford and Wrekin"
  ],
  "postcodes": [
   "TF1",
   "TF2",
   "TF3"
  ],
  "status": "Confirmed 26 Feb 2026; comes into force 27 Feb 2027",
  "key_date": "2027-02-27",
  "where": "The area set by the council (see its page)",
  "summary": "Removes the right to turn a family home into a small HMO (up to 6 people) without planning permission.",
  "impact": "From 27 Feb 2027 new small HMOs need planning permission. The council says it is confirmed.",
  "sources": [
   {
    "title": "Telford & Wrekin Council: Article 4 Direction",
    "url": "https://www.telford.gov.uk/planning-and-building-control/planning-applications-and-advice-appeals-enforcement-and-guidance/article-4-direction/"
   }
  ],
  "link": "https://www.telford.gov.uk/planning-and-building-control/planning-applications-and-advice-appeals-enforcement-and-guidance/article-4-direction/",
  "checked": "2026-11-12"
 },
 {
  "title": "Gloucester: HMO Article 4",
  "category": "Article 4 coming",
  "stage": "Coming",
  "councils": [
   "Gloucester"
  ],
  "postcodes": [
   "GL1",
   "GL2"
  ],
  "status": "Confirmed; comes into force 3 Mar 2027",
  "key_date": "2027-03-03",
  "where": "Several areas of Gloucester (council map)",
  "summary": "A confirmed non-immediate direction for small HMOs.",
  "impact": "New small HMOs in the mapped areas need planning permission from 3 Mar 2027.",
  "sources": [
   {
    "title": "Gloucester City Council: Article 4 Direction",
    "url": "https://www.gloucester.gov.uk/planning-development/article-4-direction-consultation/"
   }
  ],
  "link": "https://www.gloucester.gov.uk/planning-development/article-4-direction-consultation/",
  "checked": "2026-11-12"
 },
 {
  "title": "Erewash: HMO Article 4",
  "category": "Article 4 coming",
  "stage": "Coming",
  "councils": [
   "Erewash"
  ],
  "postcodes": [
   "DE7",
   "NG10"
  ],
  "status": "Takes effect 6 Mar 2027 (council page)",
  "key_date": "2027-03-06",
  "where": "The areas on the council's map (Ilkeston and Long Eaton areas)",
  "summary": "Erewash is removing the right to convert homes to small HMOs without permission.",
  "impact": "New small HMOs in the covered areas need planning permission from 6 Mar 2027.",
  "sources": [
   {
    "title": "Erewash Borough Council: Article 4 Direction (HMOs)",
    "url": "https://www.erewash.gov.uk/planning/planning-information/proposed-article-4-direction"
   }
  ],
  "link": "https://www.erewash.gov.uk/planning/planning-information/proposed-article-4-direction",
  "checked": "2026-11-12"
 },
 {
  "title": "Stockton-on-Tees: borough-wide HMO Article 4 (unconfirmed)",
  "category": "Article 4 coming",
  "stage": "Proposed",
  "councils": [
   "Stockton-on-Tees"
  ],
  "postcodes": [
   "TS17",
   "TS18"
  ],
  "status": "Sources conflict: one lists 22 Mar 2027, another says not yet made",
  "key_date": "2027-03-22",
  "where": "Borough-wide (proposed)",
  "summary": "A borough-wide non-immediate direction is being pursued; the date isn't confirmed by the council.",
  "impact": "Check the council's own page before relying on any date.",
  "sources": [
   {
    "title": "Planning Geek: Article 4 HMO map",
    "url": "https://www.planninggeek.co.uk/gpdo/article-4/hmos/"
   },
   {
    "title": "PlanWatch",
    "url": "https://planwatch.co.uk/guides/article-4-hmo-directions-by-council"
   }
  ],
  "link": "https://www.planninggeek.co.uk/gpdo/article-4/hmos/",
  "checked": "2026-11-12"
 },
 {
  "title": "Hertsmere (Potters Bar): HMO Article 4",
  "category": "Article 4 coming",
  "stage": "Coming",
  "councils": [
   "Hertsmere"
  ],
  "postcodes": [
   "EN6"
  ],
  "status": "Confirmed; operative 6 May 2027",
  "key_date": "2027-05-06",
  "where": "Parts of Potters Bar",
  "summary": "Made 23 Apr 2026 with a 12-month lead-in, since confirmed.",
  "impact": "New small HMOs in the covered parts of Potters Bar need planning permission from 6 May 2027.",
  "sources": [
   {
    "title": "Planning Geek: Potters Bar Article 4 confirmed",
    "url": "https://www.planninggeek.co.uk/2026/potters-bar-article-4/"
   },
   {
    "title": "Hertsmere Borough Council",
    "url": "https://www.hertsmere.gov.uk/planning-building-control/building-tree-conservation/article-4-directions/hmo-consultation-page"
   }
  ],
  "link": "https://www.planninggeek.co.uk/2026/potters-bar-article-4/",
  "checked": "2026-11-12"
 },
 {
  "title": "Three Rivers: HMO Article 4",
  "category": "Article 4 coming",
  "stage": "Coming",
  "councils": [
   "Three Rivers"
  ],
  "postcodes": [
   "WD3",
   "WD18"
  ],
  "status": "Consultation closed 16 Aug 2026; listed to start 17 Jun 2027",
  "key_date": "2027-06-17",
  "where": "The areas on the council's map",
  "summary": "Three Rivers consulted on removing the right to convert homes to small HMOs.",
  "impact": "New small HMOs would need planning permission from mid-June 2027 if confirmed.",
  "sources": [
   {
    "title": "Three Rivers District Council: Article 4",
    "url": "https://www.threerivers.gov.uk/services/planning/planning-policy/article-4"
   },
   {
    "title": "Planning Geek: Article 4 HMO map",
    "url": "https://www.planninggeek.co.uk/gpdo/article-4/hmos/"
   }
  ],
  "link": "https://www.threerivers.gov.uk/services/planning/planning-policy/article-4",
  "checked": "2026-11-12"
 },
 {
  "title": "North Tyneside: HMO Article 4 in eight wards",
  "category": "Article 4 coming",
  "stage": "Coming",
  "councils": [
   "North Tyneside"
  ],
  "postcodes": [
   "NE28",
   "NE29",
   "NE30"
  ],
  "status": "Made 6 Aug 2026; consultation closed 22 Oct 2026; needs confirming",
  "key_date": "2027-08-06",
  "where": "Eight North Tyneside wards (named in the council report)",
  "summary": "A non-immediate direction covering eight wards.",
  "impact": "New small HMOs in those wards would need planning permission from 6 Aug 2027.",
  "sources": [
   {
    "title": "North Tyneside Council report",
    "url": "https://democracy.northtyneside.gov.uk/documents/s37458/Art%204%20Direction%20HMOs%20July%202026%20-%20final%20version.pdf"
   },
   {
    "title": "Planning Geek: North Tyneside",
    "url": "https://www.planninggeek.co.uk/2026/north-tyneside-hmo-article-4/"
   }
  ],
  "link": "https://democracy.northtyneside.gov.uk/documents/s37458/Art%204%20Direction%20HMOs%20July%202026%20-%20final%20version.pdf",
  "checked": "2026-11-12"
 },
 {
  "title": "Havering: borough-wide HMO Article 4",
  "category": "Article 4 coming",
  "stage": "Coming",
  "councils": [
   "Havering"
  ],
  "postcodes": [
   "RM1",
   "RM3",
   "RM7"
  ],
  "status": "Made 20 Aug 2026; proposed start 7 Sep 2027 if confirmed",
  "key_date": "2027-09-07",
  "where": "The whole of Havering",
  "summary": "Havering proposes to require planning permission for all new HMOs across the borough.",
  "impact": "New HMOs anywhere in Havering would need planning permission from September 2027.",
  "sources": [
   {
    "title": "Havering consultation",
    "url": "https://consultation.havering.gov.uk/planning/hmo-article-4-direction-consultation/"
   },
   {
    "title": "Planning Geek: Havering",
    "url": "https://www.planninggeek.co.uk/2026/havering-hmo-article-4-direction/"
   }
  ],
  "link": "https://consultation.havering.gov.uk/planning/hmo-article-4-direction-consultation/",
  "checked": "2026-11-12"
 },
 {
  "title": "Burnley: HMO Article 4 extending to six more wards",
  "category": "Article 4 coming",
  "stage": "Expansion",
  "councils": [
   "Burnley"
  ],
  "postcodes": [
   "BB10",
   "BB11",
   "BB12"
  ],
  "status": "Made 25 Sep 2026; consultation closed 6 Nov 2026; needs confirming",
  "key_date": "2027-09-27",
  "where": "Six more wards on top of those already covered (named in the linked article)",
  "summary": "A further non-immediate direction to cover the rest of Burnley.",
  "impact": "New small HMOs in those wards would need planning permission from 27 Sep 2027.",
  "sources": [
   {
    "title": "Planning Geek: Burnley Article 4 made",
    "url": "https://www.planninggeek.co.uk/2026/burnley-hmo-article-4-made/"
   }
  ],
  "link": "https://www.planninggeek.co.uk/2026/burnley-hmo-article-4-made/",
  "checked": "2026-11-12"
 },
 {
  "title": "Liverpool: HMO Article 4 for the rest of the city",
  "category": "Article 4 coming",
  "stage": "Expansion",
  "councils": [
   "Liverpool"
  ],
  "postcodes": [
   "L15",
   "L13",
   "L18",
   "L17",
   "L11",
   "L12"
  ],
  "status": "Planned for 5 Nov 2027 if confirmed",
  "key_date": "2027-11-05",
  "where": "Every part of Liverpool not already covered. Already covered: the 2021 wards (incl. Wavertree) and, since 5 Nov 2026, five more areas incl. Orrell Park, Old Swan and part of Fazakerley",
  "summary": "A non-immediate direction to extend small-HMO controls to the whole city.",
  "impact": "From Nov 2027 any new small HMO in Liverpool would need planning permission. Existing lawful HMOs aren't affected.",
  "sources": [
   {
    "title": "Planning Geek: Liverpool HMO controls take effect",
    "url": "https://www.planninggeek.co.uk/2026/liverpool-hmo-controls/"
   },
   {
    "title": "Liverpool City Council: HMOs",
    "url": "https://liverpool.gov.uk/planning-and-building-control/planning-permission/planning-permission-for-hmos/"
   }
  ],
  "link": "https://www.planninggeek.co.uk/2026/liverpool-hmo-controls/",
  "checked": "2026-11-12"
 },
 {
  "title": "Hammersmith & Fulham: borough-wide small HMO Article 4",
  "category": "Article 4 coming",
  "stage": "Proposed",
  "councils": [
   "Hammersmith and Fulham"
  ],
  "postcodes": [
   "W6",
   "W12",
   "SW6"
  ],
  "status": "Cabinet report Feb 2026; non-immediate, about a year after it's made; no date found",
  "key_date": "2027",
  "where": "The whole borough (proposed)",
  "summary": "The council favours a borough-wide non-immediate direction for small HMOs.",
  "impact": "Expect planning permission to be needed for new small HMOs from around 2027; check for the confirmed date.",
  "sources": [
   {
    "title": "H&F cabinet report",
    "url": "https://democracy.lbhf.gov.uk/documents/s133735/Article%204%20Direction%20Small%20Houses%20In%20Multiple%20Occupation.pdf"
   },
   {
    "title": "LandlordZone",
    "url": "https://www.landlordzone.co.uk/news/london-borough-seeks-to-halt-spread-of-hmos"
   }
  ],
  "link": "https://democracy.lbhf.gov.uk/documents/s133735/Article%204%20Direction%20Small%20Houses%20In%20Multiple%20Occupation.pdf",
  "checked": "2026-11-12"
 },
 {
  "title": "Gedling (Netherfield): HMO Article 4",
  "category": "Article 4 coming",
  "stage": "Coming",
  "councils": [
   "Gedling"
  ],
  "postcodes": [
   "NG4"
  ],
  "status": "Made 6 Jul 2026; consultation closed 21 Aug 2026; must be confirmed by 6 Jul 2028",
  "key_date": "2028-07-06",
  "where": "Netherfield",
  "summary": "A direction for Netherfield, awaiting confirmation.",
  "impact": "Check the council page for the date it takes effect.",
  "sources": [
   {
    "title": "Gedling Borough Council: Netherfield Article 4",
    "url": "https://www.gedling.gov.uk/planning-and-building-control/planning/netherfield-houses-multiple-occupation-article-41-direction"
   }
  ],
  "link": "https://www.gedling.gov.uk/planning-and-building-control/planning/netherfield-houses-multiple-occupation-article-41-direction",
  "checked": "2026-11-12"
 },
 {
  "title": "Cambridge: HMO Article 4 being prepared",
  "category": "Article 4 coming",
  "stage": "Proposed",
  "councils": [
   "Cambridge"
  ],
  "postcodes": [
   "CB1",
   "CB4"
  ],
  "status": "Councillors agreed on 21 Oct 2026 to prepare it; not yet made",
  "key_date": "2028-01-03",
  "where": "To be decided",
  "summary": "A non-immediate direction is being prepared; 3 Jan 2028 is only an indicative start date.",
  "impact": "Likely to need planning permission for new small HMOs from 2028.",
  "sources": [
   {
    "title": "Planning Geek: Cambridge HMO controls approved",
    "url": "https://www.planninggeek.co.uk/2026/cambridge-hmo-controls-approved/"
   }
  ],
  "link": "https://www.planninggeek.co.uk/2026/cambridge-hmo-controls-approved/",
  "checked": "2026-11-12"
 },
 {
  "title": "Reading: HMO Article 4 could expand",
  "category": "Article 4 coming",
  "stage": "Proposed",
  "councils": [
   "Reading"
  ],
  "postcodes": [
   "RG1",
   "RG30"
  ],
  "status": "Draft; would start 12 months after it's made",
  "key_date": "2028",
  "where": "Areas proposed in the committee report",
  "summary": "Reading is considering extending its HMO controls.",
  "impact": "Watch for the direction being made; the start is a year later.",
  "sources": [
   {
    "title": "Planning Geek: Reading",
    "url": "https://www.planninggeek.co.uk/2026/reading-hmo-controls/"
   }
  ],
  "link": "https://www.planninggeek.co.uk/2026/reading-hmo-controls/",
  "checked": "2026-11-12"
 },
 {
  "title": "Newcastle: HMO Article 4 under consideration",
  "category": "Article 4 coming",
  "stage": "Proposed",
  "councils": [
   "Newcastle upon Tyne"
  ],
  "postcodes": [
   "NE4",
   "NE6"
  ],
  "status": "Under consideration; no date",
  "key_date": "",
  "where": "To be decided",
  "summary": "Newcastle is considering a further HMO direction.",
  "impact": "Early stage; watch for a decision.",
  "sources": [
   {
    "title": "Planning Geek: Newcastle",
    "url": "https://www.planninggeek.co.uk/2026/newcastle-hmo-article-4/"
   }
  ],
  "link": "https://www.planninggeek.co.uk/2026/newcastle-hmo-article-4/",
  "checked": "2026-11-12"
 },
 {
  "title": "Luton: possible HMO Article 4",
  "category": "Article 4 coming",
  "stage": "Proposed",
  "councils": [
   "Luton"
  ],
  "postcodes": [
   "LU1",
   "LU2"
  ],
  "status": "Gathering evidence; no date",
  "key_date": "",
  "where": "To be decided",
  "summary": "Luton is collecting evidence for a possible direction.",
  "impact": "Early stage; watch for a decision.",
  "sources": [
   {
    "title": "Planning Geek: Luton",
    "url": "https://www.planninggeek.co.uk/2026/luton-hmo-article-4/"
   }
  ],
  "link": "https://www.planninggeek.co.uk/2026/luton-hmo-article-4/",
  "checked": "2026-11-12"
 },
 {
  "title": "Sizewell C nuclear power station (Suffolk)",
  "category": "Major project",
  "stage": "Project underway",
  "councils": [
   "East Suffolk"
  ],
  "postcodes": [
   "IP16",
   "IP17"
  ],
  "status": "Main construction phase; formal construction began January 2024",
  "key_date": "Construction ongoing through the 2030s",
  "where": "Sizewell, near Leiston (IP16); knock-on demand in Saxmundham (IP17) and Ipswich",
  "summary": "Almost 2,000 workers on site and nearly £1bn of contracts awarded to East of England businesses by January 2026. Haul road, marine import facility, the Sizewell Link Road and the Two Village Bypass were all under construction in 2026.",
  "impact": "A large construction workforce drives demand for rooms, HMOs and short lets in towns like Leiston and Saxmundham, and further out to Ipswich. That demand tends to fall as construction winds down.",
  "sources": [
   {
    "title": "New Civil Engineer: two-year construction milestone",
    "url": "https://www.newcivilengineer.com/latest/sizewell-c-has-awarded-almost-1bn-in-local-contracts-at-two-year-mark-of-construction-16-01-2026/"
   },
   {
    "title": "Aldeburgh Town Council: construction update",
    "url": "https://www.aldeburghtowncouncil.gov.uk/2026/06/sizewell-c-construction-update/"
   }
  ],
  "link": "https://www.newcivilengineer.com/latest/sizewell-c-has-awarded-almost-1bn-in-local-contracts-at-two-year-mark-of-construction-16-01-2026/",
  "checked": "2026-11-12"
 }
]


def council_key(name: str) -> str:
    """'Bristol, City of', 'City of Bristol' and 'Bristol City Council' all become 'bristol'."""
    n = name.lower().replace("&", "and")
    for junk in (", city of", ", county of", "city of ", "county of ", " city council", " borough council",
                 " district council", " county council", " council", " metropolitan borough", " (b)"):
        n = n.replace(junk, "")
    return " ".join(n.replace(",", " ").split())


def split_councils(v) -> list[str]:
    """Comma-separated councils, keeping names like 'Bristol, City of' in one piece."""
    if not isinstance(v, str):
        return [str(x).strip() for x in (v or []) if str(x).strip()]
    out: list[str] = []
    for part in [p.strip() for p in v.replace("\n", ",").replace(";", ",").split(",")]:
        if not part:
            continue
        if out and part.lower() in ("city of", "county of"):
            out[-1] = f"{out[-1]}, {part}"
        else:
            out.append(part)
    return out


def clean_entry(d: dict) -> dict:
    """Normalises an entry from the form or the seed."""
    def lst(v):
        if isinstance(v, str):
            return [x.strip() for x in v.replace("\n", ",").split(",") if x.strip()]
        return [str(x).strip() for x in (v or []) if str(x).strip()]

    sources = d.get("sources") or []
    if isinstance(sources, str):   # "Title | url" per line, or bare urls
        parsed = []
        for line in sources.splitlines():
            if not line.strip():
                continue
            title, _, url = line.rpartition("|") if "|" in line else ("", "", line)
            url = url.strip()
            if url.startswith(("http://", "https://")):
                parsed.append({"title": title.strip() or url, "url": url})
        sources = parsed
    return {
        "id": d.get("id") or secrets.token_hex(4),
        "title": str(d.get("title") or "").strip() or "Untitled",
        "category": d.get("category") if d.get("category") in CATEGORIES else "Other",
        "councils": split_councils(d.get("councils")),
        "postcodes": [p.upper() for p in lst(d.get("postcodes"))],
        "status": str(d.get("status") or "").strip(),
        "key_date": str(d.get("key_date") or "").strip(),
        "summary": str(d.get("summary") or "").strip(),
        "impact": str(d.get("impact") or "").strip(),
        "sources": [s for s in sources if isinstance(s, dict) and str(s.get("url", "")).startswith("http")],
        "checked": str(d.get("checked") or date.today().isoformat()),
        "stage": d.get("stage") if d.get("stage") in STAGES else "",
        "where": str(d.get("where") or "").strip(),
        "link": str(d.get("link") or "").strip() if str(d.get("link") or "").startswith("http") else "",
    }


class HotList:
    """Stored in the app's SQLite database."""

    def __init__(self, db):
        self.conn = db.conn
        self.conn.execute("CREATE TABLE IF NOT EXISTS hotlist (id TEXT PRIMARY KEY, data TEXT, updated TEXT)")
        self.conn.execute("CREATE TABLE IF NOT EXISTS meta (k TEXT PRIMARY KEY, v TEXT)")
        self.conn.commit()
        self._seed()

    def _seed(self) -> None:
        row = self.conn.execute("SELECT v FROM meta WHERE k='hotlist_seed'").fetchone()
        if row and int(row[0]) >= SEED_VERSION:
            return
        done = int(row[0]) if row else 0
        for v in range(done + 1, SEED_VERSION + 1):
            for title in REPLACED_SEEDS.get(v, []):
                for e in self.all():
                    if e["title"] == title and e.get("checked") in ("2026-11-11", "2026-11-12"):
                        self.delete(e["id"])
        existing = {e["title"] for e in self.all()}
        for d in SEED:
            if d["title"] not in existing:
                self.save(clean_entry(d))
        self.conn.execute("INSERT OR REPLACE INTO meta VALUES ('hotlist_seed', ?)", (str(SEED_VERSION),))
        self.conn.commit()

    @staticmethod
    def _complete(e: dict) -> dict:
        """Fill stage / where / link for entries saved before those fields existed."""
        extra = SEED_EXTRA.get(e.get("title")) or next((d for d in SEED if d["title"] == e.get("title")), {})
        for k in ("stage", "where", "link"):
            if not e.get(k):
                e[k] = extra.get(k, "")
        if not e.get("stage"):
            e["stage"] = default_stage(e.get("category", ""))
        if not e.get("link") and e.get("sources"):
            e["link"] = e["sources"][0]["url"]
        return e

    def all(self) -> list[dict]:
        out = [self._complete(json.loads(r[0])) for r in self.conn.execute("SELECT data FROM hotlist")]
        order = {c: i for i, c in enumerate(CATEGORIES)}
        return sorted(out, key=lambda e: (order.get(e["category"], 99), e["title"].lower()))

    def get(self, entry_id: str) -> dict | None:
        r = self.conn.execute("SELECT data FROM hotlist WHERE id=?", (entry_id,)).fetchone()
        return self._complete(json.loads(r[0])) if r else None

    def save(self, entry: dict) -> dict:
        entry = clean_entry(entry)
        self.conn.execute("INSERT OR REPLACE INTO hotlist VALUES (?,?,?)",
                          (entry["id"], json.dumps(entry), date.today().isoformat()))
        self.conn.commit()
        return entry

    def delete(self, entry_id: str) -> None:
        self.conn.execute("DELETE FROM hotlist WHERE id=?", (entry_id,))
        self.conn.commit()

    @staticmethod
    def is_upcoming(e: dict, today: date | None = None) -> bool:
        """Still ahead of us: not already in force, and its date (if it has one) hasn't passed."""
        if e.get("stage") == "In force":
            return False
        if e.get("category") == "Major project":
            return True
        import re as _re
        m = _re.match(r"(\d{4}-\d{2}-\d{2})", str(e.get("key_date") or ""))
        return not m or m.group(1) >= (today or date.today()).isoformat()

    @staticmethod
    def sort_key(e: dict):
        import re as _re
        m = _re.match(r"(\d{4})(?:-(\d{2})-(\d{2}))?", str(e.get("key_date") or ""))
        when = (m.group(0) if m.group(2) else m.group(1) + "-12-31") if m else "9999"   # "2027" = some time in 2027
        return (e.get("category") == "Major project", when, e["title"].lower())

    def upcoming(self, today: date | None = None) -> list[dict]:
        return sorted((e for e in self.all() if self.is_upcoming(e, today)), key=self.sort_key)

    def past(self, today: date | None = None) -> list[dict]:
        return sorted((e for e in self.all() if not self.is_upcoming(e, today)), key=self.sort_key)

    def for_councils(self, councils: set[str]) -> list[dict]:
        wanted = {council_key(c) for c in councils}
        return [e for e in self.upcoming() if wanted & {council_key(c) for c in e["councils"]}]
