====================================================================
US GOVERNMENT H-1B SPONSORSHIP DATA  (free, public)
Downloaded from USCIS H-1B Employer Data Hub
====================================================================
Source: https://www.uscis.gov/tools/reports-and-studies/h-1b-employer-data-hub
File pattern: https://www.uscis.gov/sites/default/files/document/data/h1b_datahubexport-YYYY.csv

WHAT THIS IS
------------
The official US government record of which employers filed H-1B petitions
and how many were APPROVED vs DENIED, per fiscal year. This is the factual
"who actually sponsors visas" data that tools like MigrateMate are built on.

FILES IN THIS FOLDER
--------------------
- USCIS_H1B_Employer_DataHub_FY2023.csv   (33,333 employer rows)
- USCIS_H1B_Employer_DataHub_FY2022.csv   (59,984 rows)
- USCIS_H1B_Employer_DataHub_FY2021.csv   (60,807 rows)
- TOP_200_H1B_Sponsors_FY2023.csv         (ranked summary I generated)

COLUMNS (in the raw CSVs)
-------------------------
- Fiscal Year        : the FY (e.g. 2023)
- Employer           : company name (as filed)
- Initial Approval   : NEW H-1B petitions approved (fresh hires) <- best "they sponsor" signal
- Initial Denial     : new petitions denied
- Continuing Approval: extensions/transfers approved (existing H-1B workers)
- Continuing Denial  : extensions denied
- NAICS              : industry code
- Tax ID             : last 4 of employer tax id
- State / City / ZIP : worksite location

HOW TO READ IT
--------------
- High "Initial Approval" = company actively hires & sponsors NEW H-1B workers
  (most useful for a job seeker who needs sponsorship).
- "Continuing" only = they keep existing H-1B staff but may not sponsor new hires.
- A company can appear in multiple rows (different worksite locations).

TOP H-1B SPONSORS FY2023 (by total approvals)
---------------------------------------------
1. Amazon  2. Cognizant  3. TCS  4. Infosys  5. Google  6. Microsoft
7. Apple  8. Meta  9. JPMorgan  10. Deloitte ... (full list: TOP_200 file)
Note: heavy presence of Indian IT firms (TCS, Infosys, HCL, Wipro, Tech Mahindra,
LTIMindtree) - directly relevant for Indian students/workers.

OTHER FREE GOVERNMENT SOURCES (not downloaded here)
---------------------------------------------------
- DOL OFLC LCA Disclosure Data (RICHER: adds job title + WAGE + worksite):
  https://www.dol.gov/agencies/eta/foreign-labor/performance
  (large .xlsx files, ~100s of MB per fiscal year)
- PERM data (green-card sponsorship) - same DOL page.
- Pre-parsed/searchable web tools: h1bdata.info , h1bgrader.com

HOW WE USE THIS IN THE PORTAL (M2 sponsorship layer)
----------------------------------------------------
When we scrape a Greenhouse/Lever/Ashby job, look up the company name here and
tag the job: sponsors_h1b = yes (N approvals last year). Then use as a KNOCKOUT
filter for visa-needing candidates (e.g. Indian F-1/OPT/H-1B students), so we
only auto-apply to employers that actually sponsor. (See handoff doc Section 15.)

CAVEATS
-------
- Approval record != guarantee they'll sponsor YOU or this specific role now.
- Data lags (published per fiscal year / quarter).
- Company-name matching is imperfect ("Google LLC" vs "Google Inc").
- FY2024/2025 not at the same URL pattern (USCIS updates naming); hub goes to FY2026 Q2.
