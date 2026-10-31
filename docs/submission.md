Report Navigator
5 . 1 B A C K G R O U N D
Journalists, policy researchers and district officials often need one exact number from long annual
statistics reports. These reports run to hundreds of pages of tables and text, and generic chatbots
answer confidently and wrongly.
A newsroom wants a small, offline assistant. It must give the exact figure, cite the page it came
from, and say NOT_FOUND when the report does not contain the answer.
5 . 2 P R O B L E M F R A M I N G
Task: question answering over a long PDF with tables, page citations and abstention (retrieval-
augmented generation).
For each question return: the exact integer answer as printed, or NOT_FOUND; the 1-based PDF
page number that supports it; and a confidence.
At scoring time your system receives a different report of the same family: similar structure,
different year, and some pages are scanned images without a text layer. Questions are new and
may be phrased differently.
5 . 3 D A T A S E T
report_A.pdf : a 272-page official statistics report with narrative text and many tables.
questions_with_answers.jsonl : 50 example questions (45 answerable, 5 unanswerable). Fields:
id, question, answer, answer_type, gold_pages, qtype.
sample_answers.jsonl : output format, one JSON per line: id, answer, page, confidence.
Answers are integers written without commas, or NOT_FOUND. Question types cover city-level,
state-level and national figures, breakdowns by category, and unanswerable questions.
5 . 4 O B J E C T I V E A N D E N D G O A L
Exact answers: no rounding and no hallucination.
Correct page citations.
Honest abstention: never invent a number for an unanswerable question.
•
•
•
•
•
•
•
•
•
HACKTOBERFEST HACK DAY LUCKNOW AI COMMUNITY LUCKNOW
Hacktoberfest Hack Day Lucknow · AI Community Lucknow 19 / 26
5 . 5 K P I S
METRIC DEFINITION BETTER ROLE
Score 0.75 × EM + 0.25 × CitationAcc Higher Primary
Exact match
(EM)
Answer equals gold after removing commas and spaces;
NOT_FOUND must match exactly
Higher Component
Citation
accuracy
Page is in the gold pages; for unanswerable questions, correct
when answer is NOT_FOUND
Higher Component
Hallucination
rate
Share of unanswerable questions that receive a number Lower Secondary; tie-
break 1
Answerable
recall
Share of answerable questions given a non-NOT_FOUND
answer
Higher Reported only
5 . 6 B A S E L I N E A N D S C O R E B A N D S
BAND SCORE EM
Lazy ≤ 0.30 (find entity page, return first number) ≤ 0.15
Good ≥ 0.60 (estimate) ≥ 0.55
Excellent ≥ 0.80 (estimate) ≥ 0.78
Always answering NOT_FOUND scores about 0.06. Finding the right page is easy; extracting the
right cell is the real task.
5 . 7 S U B M I S S I O N F O R M A T
python predict.py --pdf {pdf_path} --questions {questions_jsonl} --output {answers_jsonl}
Input: one JSON per line {"id", "question"} .
Output: one JSON per input id {"id", "answer", "page", "confidence"} . answer is digits only
(no commas, spaces or units) or exactly NOT_FOUND; page is an integer from 1 to the page
count, or null for NOT_FOUND; confidence in 0–1.
A missing id, a comma in an answer or an out-of-range page makes that question wrong; a
malformed line makes the run invalid.
Limits: 20 minutes in total including PDF ingestion; 2 CPU; 6 GB RAM; no network; local model
files ≤ 3 GB. The index must be built at run time from --pdf.
{"id": "P000", "answer": "351", "page": 101, "confidence": 0.92}
{"id": "P043", "answer": "NOT_FOUND", "page": null, "confidence": 0.70}
5 . 8 S C O R I N G R U N L I M I T
4 validation runs, 20-minute cooldown, 1 final selection.
•
•
•
•
•
HACKTOBERFEST HACK DAY LUCKNOW AI COMMUNITY LUCKNOW
Hacktoberfest Hack Day Lucknow · AI Community Lucknow 20 / 26
Unlimited schema checks (5 public questions on report_A.pdf), at most one every 5 minutes.
Scoring uses a hidden test set plus robustness checks. Your pipeline must not crash or hang on
pages without a text layer.
5 . 9 W H A T Y O U W I L L B U I L D
A RAG system (search plus optional small local LLM or table logic) that finds the relevant parts of
the report and returns the answer.
Page references with every answer so it can be checked.
A simple interface (chat, web page or CLI) to ask questions.
5 . 1 0 B O N U S I D E A S
Scanned pages: OCR support for image-only pages with Tesseract (free).
Calibrated confidence (machine-checked): bonus if EM on your 50% most-confident answers is
at least 0.15 above overall EM.
Evidence view: a demo UI that highlights the table row on the cited page.
5 . 1 1 R U L E S A N D A N T I - G A M I N G
Cite the 1-based PDF page index, not the number printed in the page footer.
Shipping pre-extracted text, tables or answers from any report is disqualifying; PDF-derived text
files over 1 MB in your repo are flagged.
Cloud LLM APIs cannot be used at scoring time (no network). A small local model downloaded
during the build is allowed.
Audit tolerance: Score within 0.03