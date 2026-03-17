"""
AI prompts and Pydantic response models for Grok analysis.

This module contains all prompts used for:
1. Website Assessment - Finding the best website for an agent
2. Team Page Selection - Identifying team/agent listing pages
3. Team Size Analysis - Counting team members and extracting details
4. Team/Brokerage Extraction - Extracting team and brokerage names
"""

from typing import List, Literal, Optional

from pydantic import BaseModel, Field


# =============================================================================
# PROMPT 1: Website Assessment
# =============================================================================

WEBSITE_ASSESSMENT_PROMPT = """Your task is to identify one correct website from the Serper API JSON results.

Compare the results with the given input details:
- Organization/Team name: {organization_name}
- Full name: {full_name}
- Phone number: {phone}
- Email: {email}
- Location: {location}
- Brokerage: {brokerage}
- Known website: {website_clean}
{exclude_text}

Serper API JSON results:
{serper_results}

**BE EXTREMELY LENIENT WHILE EVALUATING.**

IMPORTANT RULES:
1. **The URL should NOT be a pure brokerage URL like kw.com, realtor.com, remax.com, compass.com or any other brokerage URL.
2. But it CAN be a sub-URL like johnsmith.kw.com or team.remax.com (these are VALID).
3. If you find a result that matches the agent's name and location, or matches the organization name, you MUST select it even if you are not 100% certain.
4. Preference should be given to personal or team websites (e.g., johnsmithrealty.com) over generic brokerage subpages if both are present.
5. If the agent's name appears in the title or snippet of a result, it is likely the correct website.
6. Only return an empty URL if the results are completely irrelevant (e.g., completely different industry or different person in a different state).
7. Do NOT return "N/A" values - leave fields empty instead.
8. NEVER return social media or IDX-only domains (linkedin.com, facebook.com, instagram.com, twitter.com, idxbroker.com, etc.).

Return ONLY valid JSON in this exact format (no markdown, no extra text):
{{
  "url": "selected_website_url_or_empty_string",
  "reason": "brief_explanation"
}}"""


class WebsiteAssessment(BaseModel):
    """Website assessment result from Grok."""

    url: str = Field(
        default="",
        description="Selected website URL or empty string if no match found",
    )
    reason: str = Field(
        default="",
        description="Brief explanation of why this website was selected",
    )


# =============================================================================
# PROMPT 2: Team Page Selection
# =============================================================================

TEAM_PAGE_SELECTION_PROMPT = """You are given a list of candidate URLs for a single company. Your job is to return **one** URL that is the best match for a page that lists team members/agents (names, roles, photos, bios).

Candidate URLs:
{urls}

Scoring rules (apply in order, stop when you find the best match):

1. **Exact team/agents page patterns (HIGHEST PRIORITY)**:
   - URL contains: /team, /our-team, /meet-the-team, /team-members, /people, /leadership, /staff, /crew, /board, /agents, /real-estate-agents, /agent-list
   - Prefer plural tokens ("team", "agents", "people") over singular

2. **Industry-specific agent pages**:
   - For real estate: /agents, /our-agents, /realtors, /brokers, /advisors, /agent-search, /find-agent

3. **Subdirectories and slugs**:
   - Prefer: /about/team, /company/team, /who-we-are/team over generic pages

4. **Page title heuristics** (if available):
   - Titles with: "Team", "Meet the Team", "Our Team", "Leadership", "People", "Agents"

5. **Fallback to About**:
   - If no team page found: /about, /about-us, /company, /who-we-are, /contact, /contact-us, /contact-me

6. **Last resort**:
   - If none match, return empty string

⚠️ NEVER return LinkedIn, Facebook, Instagram, Twitter, or IDX-only pages (idxbroker.com, boomtownroi.com, etc.). Those are not valid team listings.

Return a single JSON object (not an array) with these fields:
- selectedUrl: the single best URL string (or "" if none)
- reasoning: 1-3 sentences explaining which pattern matched

Example output:
{{
  "selectedUrl": "https://example.com/meet-the-team",
  "reasoning": "The URL contains 'meet-the-team', which strongly indicates a page showcasing team members. This matches the highest-priority rule."
}}

Return ONLY valid JSON (no markdown, no extra text)."""


class TeamPageSelection(BaseModel):
    """Team page selection result from Grok."""

    selectedUrl: str = Field(
        default="",
        description="Single best URL for team/agents or empty string if none found",
    )
    reasoning: str = Field(
        default="",
        description="Concise 1-3 sentence explanation: which token(s) or rule matched",
    )


# =============================================================================
# PROMPT 3: Team Size Analysis
# =============================================================================

TEAM_SIZE_ANALYSIS_PROMPT = """You are an expert data extraction engine for real-estate team analysis.
Your ONLY job is to determine:
1) teamSize (integer)
2) teamMembers (list of extracted people)
3) confidence (HIGH | MEDIUM | LOW)
using ONLY the information in the provided markdown.

====================================================
AGENT FULL NAME FROM DATABASE:
{agent_full_name}
====================================================

====================================================
INPUT MARKDOWN:
{markdown_content}
====================================================

### EXTRACTION RULES
Count ONLY real humans (names, roles, bios, profile cards, staff photos).
If the page explicitly states a number ("50 agents", "team of 22"), USE that number.
If employees are listed individually, count them one by one.
Deduplicate people by name + email + phone.
Extract for each identified human:
    • name (required)
    • email (optional — normalize obfuscated emails like "name [at] domain [dot] com")
    • phone (optional — normalize spacing, keep country code)
    • designation (optional — "realtor", "broker", "marketing", etc.)
Ignore generic emails like "info@company.com" unless it is clearly tied to a specific person.

### AGENT DESIGNATION EXTRACTION (IMPORTANT)
The agent's full name from the database is provided above: "{agent_full_name}"

When extracting team members, if you find a team member whose name matches (or closely matches) the agent's full name "{agent_full_name}", you MUST:
1. Extract that person's designation/role/title from the page
2. Include it in the teamMembers array for that matching person
3. Be flexible with name matching (handle variations like "John Smith" vs "John A. Smith", nicknames, middle names, etc.)

If the agent's name is not found in the team members list, or if no designation is available for that person, the designation field should be an empty string "" for that team member.

**BE EXTREMELY LENIENT IN IDENTIFYING PEOPLE.**
Look for ANY professional name associated with bio/contact info rather than defaulting to 0 when standard "profile cards" are missing. If you see a name with a title, or a name with an email/phone, count it as a person.

### HANDLING EMPTY OR NON-TEAM PAGES
Apply the following rules:

1. **If ZERO human names, ZERO roles, and NO professional bios exist → but the page clearly belongs to a specific real estate agent (e.g., personal branding, personal contact info, personal logo) → teamSize = 1**
   Extract the owner if possible, otherwise leave teamMembers empty but set teamSize = 1.

2. **If the page looks like a SINGLE-PERSON professional profile**
   signals include:
   - a person's full name centered at top
   - first-person bio ("I have served this region…")
   - one dedicated headshot
   - personal certifications, awards
   - **Even if no explicit name is found but the site is clearly a personal agent site → teamSize = 1.**
   THEN → teamSize = 1 and extract that person.

3. **If corporate page (About us, Company philosophy, contact info, mission, careers)**
   and **NO names appear** → but still page looks like a corporate page → teamSize = 1.

4. NEVER hallucinate team members or count unknown staff.

### DECISION LOGIC (VERY IMPORTANT)
If explicit number exists → prefer explicit number.
If list of names exists → count names.
If ambiguous → choose the LOWER number, not higher.

### OUTPUT FORMAT (STRICT JSON)
Return ONLY the following JSON:

{{
  "teamSize": number,
  "teamMembers": [
    {{
      "name": "string",
      "email": "string | ''",
      "phone": "string | ''",
      "designation": "string | ''"
    }}
  ],
  "confidence": "HIGH | MEDIUM | LOW",
  "reasoning": "1 sentence explaining why the teamSize was chosen"
}}

### IMPORTANT
The JSON MUST be valid.
No commentary outside the JSON.
No added assumptions."""


class TeamMember(BaseModel):
    """Individual team member extracted from a page."""

    name: str = Field(description="Full name of the team member")
    email: str = Field(default="", description="Email address if found")
    phone: str = Field(default="", description="Phone number if found")
    designation: str = Field(default="", description="Role/title if found")


class TeamSizeAnalysis(BaseModel):
    """Team size analysis result from Grok."""

    teamSize: int = Field(
        default=0,
        description="Total count of team members, or 0 if unable to determine",
    )
    confidence: Literal["LOW", "MEDIUM", "HIGH"] = Field(
        default="LOW",
        description="Confidence level of the estimate",
    )
    teamMembers: List[TeamMember] = Field(
        default_factory=list,
        description="Array of individual team member details",
    )
    reasoning: str = Field(
        default="",
        description="1 sentence explaining why the teamSize was chosen",
    )


# =============================================================================
# PROMPT 4: Team/Brokerage Name Extraction
# =============================================================================

TEAM_BROKERAGE_EXTRACTION_PROMPT = """You are an expert AI in extracting structured real estate data from website markdown.

Task: From the input data, extract two distinct fields:

team_name

brokerage_name

Guidelines:

The input may contain combined or separated values using characters like |, -, /, •, or similar separators.

If the team name and brokerage are combined, intelligently split them. Typically, the team name appears first and the brokerage appears second, but validate using context words like "Team", "Group", "Associates", or known brokerage keywords (e.g., Keller Williams, Compass, RE/MAX).

Remove extra whitespace, special characters, or redundant labels.

If only one entity is present, return it in the most probable key and leave the other as null.

CRITICAL: Output strictly in raw JSON format. Do not use markdown formatting, code blocks, or backticks. Do not include any other text.

Website homepage URL: {homepage_url}
Input: {content}

Example Inputs & Outputs:

Input:
"Howard Hanna | Leonard Corsi Team"

Output:
{{
  "team_name": "Leonard Corsi Team",
  "brokerage_name": "Howard Hanna"
}}

Input:
"Lupole & Allen Team - AtProperties"

Output:
{{
  "team_name": "Lupole & Allen Team",
  "brokerage_name": "AtProperties"
}}

Input:
"Keller Williams Realty"

Output:
{{
  "team_name": null,
  "brokerage_name": "Keller Williams Realty"
}}

Return ONLY valid JSON (no markdown, no extra text):"""


class TeamBrokerageExtraction(BaseModel):
    """Team and brokerage name extraction result from Grok."""

    team_name: Optional[str] = Field(
        default=None,
        description="The name of the real estate team, group, or associates",
    )
    brokerage_name: Optional[str] = Field(
        default=None,
        description="The name of the brokerage firm",
    )


# =============================================================================
# Prompt Formatting Helpers
# =============================================================================


def format_website_assessment_prompt(
    organization_name: str,
    full_name: str,
    phone: str,
    email: str,
    location: str,
    brokerage: str,
    website_clean: str,
    serper_results: str,
    exclude_url: Optional[str] = None,
) -> str:
    """Format the website assessment prompt with agent details."""
    exclude_text = f"\nDo NOT return: {exclude_url}\n" if exclude_url else ""

    return WEBSITE_ASSESSMENT_PROMPT.format(
        organization_name=organization_name or "N/A",
        full_name=full_name or "N/A",
        phone=phone or "N/A",
        email=email or "N/A",
        location=location or "N/A",
        brokerage=brokerage or "N/A",
        website_clean=website_clean or "N/A",
        serper_results=serper_results,
        exclude_text=exclude_text,
    )


def format_team_page_selection_prompt(urls: List[str]) -> str:
    """Format the team page selection prompt with candidate URLs."""
    import json

    return TEAM_PAGE_SELECTION_PROMPT.format(
        urls=json.dumps(urls[:100], indent=2),
    )


def format_team_size_analysis_prompt(
    markdown_content: str,
    agent_full_name: str = "",
) -> str:
    """Format the team size analysis prompt with page content."""
    return TEAM_SIZE_ANALYSIS_PROMPT.format(
        markdown_content=markdown_content,
        agent_full_name=agent_full_name or "",
    )


def format_team_brokerage_extraction_prompt(
    content: str,
    homepage_url: str,
) -> str:
    """Format the team/brokerage extraction prompt."""
    return TEAM_BROKERAGE_EXTRACTION_PROMPT.format(
        content=content,
        homepage_url=homepage_url,
    )
