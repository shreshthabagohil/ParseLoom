"""
Generates a fresh batch of randomized mock resumes -- different names,
skill combos, CGPA formats, and structure each run -- to stress-test the
web app (and CLI) against content that's never been seen before, per
request. Not deterministic on purpose. Output: data/random_mocks/.
"""
import os
import random

import fitz

OUT_DIR = "data/random_mocks"
os.makedirs(OUT_DIR, exist_ok=True)

FIRST_NAMES = ["Aditi", "Rohan", "Kavya", "Nikhil", "Ishita", "Varun", "Sneha", "Aryan"]
LAST_NAMES = ["Sharma", "Patel", "Reddy", "Nair", "Gupta", "Iyer", "Chatterjee", "Menon"]
SKILL_POOL = ["Python", "JavaScript", "React.js", "Node.js", "SQL", "MongoDB", "Docker",
              "Git", "GitHub", "AWS", "TypeScript", "Redux", "GraphQL", "Jest", "Firebase"]
DEGREES = ["B.Tech Computer Science", "B.E. Information Technology", "B.Sc Computer Applications"]
COLLEGES = ["Kirloskar Institute", "St. Xavier College of Engineering", "National Institute of Tech, Surat"]
CGPA_STYLES = [
    lambda: f"CGPA: {round(random.uniform(6.0, 9.5), 1)}/10",
    lambda: f"Percentage: {random.randint(60, 92)}%",
    lambda: f"GPA: {round(random.uniform(2.5, 3.9), 1)}/4.0",
]


def random_resume_lines():
    name = f"{random.choice(FIRST_NAMES)} {random.choice(LAST_NAMES)}"
    skills = random.sample(SKILL_POOL, k=random.randint(4, 8))
    return [
        name.upper(),
        f"{name.lower().replace(' ', '.')}@email.com | +91 {random.randint(90000,99999)} {random.randint(10000,99999)}",
        "",
        "EDUCATION",
        f"{random.choice(DEGREES)}, {random.choice(COLLEGES)}, {random.randint(2023,2026)}",
        random.choice(CGPA_STYLES)(),
        "",
        "SKILLS",
        ", ".join(skills),
        "",
        "PROJECTS",
        f"Project Alpha -- built using {skills[0]} and {skills[1] if len(skills)>1 else skills[0]}, "
        f"deployed for a small user base with automated testing and continuous integration.",
        f"Project Beta -- a second project using {random.choice(skills)}, focused on solving a "
        f"real problem for a student club with a small but active group of daily users.",
        "",
        "EXPERIENCE",
        f"Intern, RandomCo, {random.randint(2023,2025)}",
        f"Worked on {random.choice(skills)}-based internal tools, collaborated with a small team "
        f"and shipped two minor features during the internship period.",
        "",
        "CERTIFICATIONS",
        f"{random.choice(skills)} Fundamentals Certificate",
    ], name


def make_pdf(filename, lines):
    doc = fitz.open()
    page = doc.new_page()
    y = 50
    for line in lines:
        if y > 730:
            page = doc.new_page()
            y = 50
        page.insert_text((50, y), line, fontsize=11)
        y += 16
    data = doc.tobytes()
    doc.close()
    with open(os.path.join(OUT_DIR, filename), "wb") as f:
        f.write(data)


def main():
    random.seed()  # true randomness, not reproducible on purpose
    count = 6
    names = []
    for i in range(count):
        lines, name = random_resume_lines()
        fname = f"random_{i+1}_{name.split()[0].lower()}.pdf"
        make_pdf(fname, lines)
        names.append(fname)
    print(f"Generated {count} random mock resumes in {OUT_DIR}/:")
    for n in names:
        print(" ", n)


if __name__ == "__main__":
    main()
