# Quick local survey sanity check

These manual steps verify the CULTURE_DISCRIMINATION survey rails:

1. Start the server (e.g., `docker-compose up`) and open `http://127.0.0.1:8000/CULTURE_DISCRIMINATION/TESTSESSION`.
2. Answer Q1 with `No` — the engine should automatically skip Q2 and move to Q3.
3. Answer Q3 with `No` — the engine should automatically skip Q4 and move to Q5.
4. Continue through the remaining items. No question should repeat once answered or skipped.
5. After Q7, the survey should end with: `The survey is complete. Please proceed to the next page.---END---`.
