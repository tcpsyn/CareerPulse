import logging

from app.ai_client import AIClient, parse_json_response

logger = logging.getLogger(__name__)


PROFILE_PARSE_PROMPT = """Extract structured profile data from this resume. Pull out every fact you can find.

RESUME:
{resume}

Return ONLY valid JSON with this exact structure (use null for fields not found):
{{
    "personal": {{
        "first_name": "...",
        "last_name": "...",
        "email": "...",
        "phone": "...",
        "address_city": "...",
        "address_state": "...",
        "address_country_name": "...",
        "linkedin_url": "...",
        "github_url": "...",
        "portfolio_url": "...",
        "website_url": "..."
    }},
    "work_history": [
        {{
            "job_title": "...",
            "company": "...",
            "location_city": "...",
            "location_state": "...",
            "start_month": 1,
            "start_year": 2020,
            "end_month": null,
            "end_year": null,
            "is_current": 1,
            "description": "Brief summary of role and key achievements"
        }}
    ],
    "education": [
        {{
            "school": "...",
            "degree_type": "bachelors",
            "field_of_study": "...",
            "grad_year": 2018,
            "gpa": null
        }}
    ],
    "skills": [
        {{
            "name": "...",
            "years_experience": null,
            "proficiency": "advanced"
        }}
    ],
    "certifications": [
        {{
            "name": "...",
            "issuing_org": "...",
            "date_obtained": "2023-01-01"
        }}
    ],
    "languages": [
        {{
            "language": "English",
            "proficiency": "native"
        }}
    ]
}}

Rules:
- Extract ALL work history entries, ordered most recent first
- For skills, extract technical skills, tools, frameworks, and languages mentioned
- proficiency for skills: beginner/intermediate/advanced/expert (infer from context)
- degree_type must be one of: high_school, associates, bachelors, masters, mba, jd, md, phd, other
- language proficiency: native/fluent/conversational/basic
- For work history descriptions, summarize key responsibilities and achievements in 1-3 sentences
- Use null (not empty string) for fields not found in the resume
- Do NOT fabricate data — only extract what is explicitly stated"""


async def parse_resume_to_profile(client: AIClient, resume_text: str) -> dict:
    try:
        prompt = PROFILE_PARSE_PROMPT.format(resume=resume_text)
        raw = await client.chat(prompt, max_tokens=4000)
        result = parse_json_response(raw)
        return result
    except Exception as e:
        logger.error(f"Resume profile parse failed: {e}")
        return {}

ANALYSIS_PROMPT = """Analyze this resume and determine what jobs this person is best suited for.

RESUME:
{resume}

Return ONLY valid JSON with this exact structure:
{{
    "search_terms": [
        "term 1",
        "term 2"
    ],
    "job_titles": [
        {{
            "title": "Senior DevOps Engineer",
            "why": "20+ years infrastructure experience, strong AWS/K8s/Terraform skills"
        }}
    ],
    "key_skills": ["skill 1", "skill 2"],
    "seniority": "senior/staff/lead/principal",
    "summary": "Brief 2-3 sentence summary of what makes this candidate stand out and what roles they'd excel in.",
    "ats_score": 85,
    "ats_issues": ["issue 1", "issue 2"],
    "ats_tips": ["tip 1", "tip 2"]
}}

Guidelines:
- search_terms: 8-15 specific phrases to use as search queries on job boards (e.g. "senior devops engineer remote", "SRE remote", "platform engineer remote")
- job_titles: 5-10 job titles with a brief explanation of WHY this resume fits each role
- key_skills: The candidate's top 10-15 technical and domain skills extracted from the resume
- seniority: The appropriate seniority level based on years of experience and roles held
- summary: What makes this candidate unique and what types of roles they should target
- Focus on the candidate's strongest skills and most recent experience
- Include both broad and niche search terms
- Add "remote" to search terms where appropriate
- Consider the seniority level evident in the resume
- ats_score: Rate 0-100 how ATS-friendly this resume's CONTENT and STRUCTURE is based on the text you can see. Evaluate:
  * Does it have clearly labeled standard sections (SUMMARY, TECHNICAL SKILLS, EXPERIENCE, EDUCATION, CERTIFICATIONS)?
  * Are skills listed in a dedicated section with clear categories?
  * Are job titles, company names, and dates clearly structured?
  * Does it use strong action verbs and quantified achievements?
  * Is keyword density good for the target roles?
  * Score 90+ if it has all standard sections, dedicated skills section, clear formatting
  * Score 70-89 if mostly good but missing some elements
  * Score below 70 if major structural issues
- ats_issues: List ONLY specific issues you can actually identify in the text. Do NOT guess about visual formatting you cannot see.
- ats_tips: Actionable content/structure suggestions based on what you observe in the text"""


async def analyze_resume(client: AIClient, resume_text: str) -> dict:
    try:
        prompt = ANALYSIS_PROMPT.format(resume=resume_text)
        raw = await client.chat(prompt, max_tokens=2048)
        result = parse_json_response(raw)
        return {
            "search_terms": result.get("search_terms", []),
            "job_titles": result.get("job_titles", []),
            "key_skills": result.get("key_skills", []),
            "seniority": result.get("seniority", ""),
            "summary": result.get("summary", ""),
            "ats_score": result.get("ats_score", 0),
            "ats_issues": result.get("ats_issues", []),
            "ats_tips": result.get("ats_tips", []),
        }
    except Exception as e:
        logger.error(f"Resume analysis failed: {e}")
        return {"search_terms": [], "job_titles": [], "key_skills": [],
                "seniority": "", "summary": "", "ats_score": 0,
                "ats_issues": [], "ats_tips": []}
