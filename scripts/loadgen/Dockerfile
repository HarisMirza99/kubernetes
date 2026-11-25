# Load generator image: httperf + a session file of random POST /api/emi requests
FROM ubuntu:22.04
RUN apt-get update && apt-get install -y --no-install-recommends httperf python3 && rm -rf /var/lib/apt/lists/*
WORKDIR /work
COPY make_sessions.py .
RUN python3 make_sessions.py
ENTRYPOINT ["httperf"]
