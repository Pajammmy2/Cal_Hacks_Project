# Apify Python base image (Python 3.13, non-root user "myuser")
FROM apify/actor-python:3.13

USER myuser

COPY --chown=myuser:myuser requirements.txt ./

RUN echo "Python version:" \
 && python --version \
 && pip install --no-cache-dir -r requirements.txt \
 && echo "All installed Python packages:" \
 && pip freeze

COPY --chown=myuser:myuser . ./

RUN python3 -m compileall -q src/

CMD ["python3", "-m", "src"]
