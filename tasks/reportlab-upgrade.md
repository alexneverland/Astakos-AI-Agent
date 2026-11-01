# ReportLab upgrade verification — 2026-11-01

Scope: refresh the old ReportLab dependency PR #14 from its proposed 5.0.0 to
5.1.0, retaining the native PDF writer and default security settings.
Integration baseline: e030f6a7df9e69c63cbf03958bda08ffb9f86f29.
Original PR head: 504d8c05a16b5111dfd41b4290cef05e1eafe77b.

## Reason and compatibility

The official 5.1 notes describe newer restricted-evaluation fixes than 5.0.0.
The 5.0 notes document default denial of untrusted image URLs and removal of
legacy renderPM/pyRXP backends. Astakos uses neither removed backend nor a custom
trustedHosts/trustedSchemes/evaluation setting. No permissive settings are added.
ReportLab is used by astakos_skills/file_generator.py::generate_pdf.
Its requirement Python >=3.9,<4 includes the release image's Python 3.11.
Candidate forward/reverse installed dependency metadata has no conflicts.

## Offline evidence

- Baseline ReportLab 4.5.1: 30 focused cases pass; the two new native title/header
  remote-image cases fail because they reach the mocked transport boundary.
- Candidate ReportLab 5.1.0: all 39 focused cases pass, including native PDF
  sections/bullets/literal text, all lines across multiple pages, Unicode metadata,
  default URL denial, existing document/PDF tests and API upload tests.
- These tests mock only transport and localization where needed; they read actual
  generated PDFs through pypdf. No cloud/provider call or live user data is used.
- Linux/Python 3.11 smoke passed in a disposable read-only container with network
  disabled and offline wheels: multi-page PDF, Unicode metadata and body with an
  explicitly registered bundled font, and default remote-URL denial. This is a
  library/platform check, not a full Astakos release-image startup test.
- Existing Unicode metadata is verified; this is not a claim that the native
  writer's default Helvetica font supports arbitrary Unicode body glyphs.

No production PDF code, global ReportLab settings, credentials, live stores,
Dockerfiles, supervisors, release tags or publishing behavior changed.
The local project venv remains at 4.5.1 pending the user's merge/install decision.

## Upstream sources

- https://docs.reportlab.com/releases/notes/whats-new-50/
- https://docs.reportlab.com/releases/notes/whats-new-51/
- https://pypi.org/project/reportlab/5.1.0/
