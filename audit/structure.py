"""
structure.py: the four audit areas and their sub-sections.

Every issue produced by any check module carries a "group" equal to one of the
sub-section names below. areas.py uses this table to place the issue, score
the sub-section, and score the area. Adding a check to the report means giving
it one of these group names.
"""

# Sub-section names
SG_FIVE = "The 5-Second Test"
SG_LOGISTICS = "Practical Logistics"
SG_KIDS = "Family and Kids"
SG_WELCOME = "Welcome and Plain Language"

SG_SERVICE = "Service Details"
SG_EXPECT = "What to Expect"
SG_BELIEFS = "Beliefs and Leadership"
SG_SERMON = "Sermon Media"

SG_MOBILE = "Mobile-First Navigation"
SG_BRAND = "Visual and Brand Consistency"
SG_LINKS = "Links, Forms and Embeds"

SG_LOCAL = "Google Business Profile and Local Presence"
SG_SEO = "Search Optimization"
SG_SPEED = "Site Speed"
SG_A11Y = "Accessibility"

AREAS = [
    {
        "key": "visitor",
        "name": "First-Time Visitor and Clarity",
        "subtitle": "Can a stranger tell who you are, when to come, and what happens next?",
        "subgroups": [
            {"name": SG_FIVE, "subtitle": "Name, city, denomination, times, next step"},
            {"name": SG_LOGISTICS, "subtitle": "Address, parking, entrances, accessibility"},
            {"name": SG_KIDS, "subtitle": "Ages, check-in, safety"},
            {"name": SG_WELCOME, "subtitle": "No spotlight, no insider jargon"},
        ],
    },
    {
        "key": "content",
        "name": "Essential Content and Messaging",
        "subtitle": "Does the site answer the questions a visitor actually has?",
        "subgroups": [
            {"name": SG_SERVICE, "subtitle": "Sunday, midweek, and special services"},
            {"name": SG_EXPECT, "subtitle": "Plan a Visit page, length, dress, worship feel"},
            {"name": SG_BELIEFS, "subtitle": "Beliefs, mission, and who leads"},
            {"name": SG_SERMON, "subtitle": "Recent sermons and live stream"},
        ],
    },
    {
        "key": "ux",
        "name": "User Experience and Design",
        "subtitle": "Does it work and look right on a phone?",
        "subgroups": [
            {"name": SG_MOBILE, "subtitle": "Menus, buttons, giving"},
            {"name": SG_BRAND, "subtitle": "Logo, fonts, colors, photos"},
            {"name": SG_LINKS, "subtitle": "Dead ends, broken embeds, stale details"},
        ],
    },
    {
        "key": "technical",
        "name": "Technical Health and Local SEO",
        "subtitle": "Can people find the church, and does the site load and work for everyone?",
        "subgroups": [
            {"name": SG_LOCAL, "subtitle": "Profile links, schema markup, phone and address"},
            {"name": SG_SEO, "subtitle": "Titles, city keywords, URLs, sitemap"},
            {"name": SG_SPEED, "subtitle": "Page load, Google PageSpeed (mobile)"},
            {"name": SG_A11Y, "subtitle": "Alt text, labels, mobile usability"},
        ],
    },
]

GROUP_TO_AREA = {sg["name"]: area["key"] for area in AREAS for sg in area["subgroups"]}
