"""Creates sessions.txt for httperf --wsesslog: 1000 one-request sessions, each a POST /api/emi
with RANDOM valid inputs (so every request is a different calculation written to MongoDB)."""
import random
random.seed(584)
with open("sessions.txt", "w") as f:
    for _ in range(1000):
        P = random.randint(10_000, 5_000_000)
        rate = round(random.uniform(5, 25), 2)
        n = random.randint(6, 360)
        f.write(f"/api/emi method=POST contents='P={P}&rate={rate}&n={n}'\n\n")
