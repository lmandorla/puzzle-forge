You write a Python program that independently computes the answer to a math puzzle. Its result will be compared with a separate human-style solution, so it is most valuable when it models the puzzle's rules literally rather than applying a clever formula: enumerate the actual objects, simulate the actual process state by state, or compute exact probabilities over every outcome.

Requirements for the program:
- Standalone Python 3, using only the standard library, numpy and sympy. It has no network or file access, and must not start other processes.
- Deterministic and exact where possible: use fractions.Fraction or sympy for exact values, and high-precision numerics (for example sympy or mpmath integration) for continuous quantities. Do not use random sampling.
- Must finish in under 20 seconds and use under 400 MB of memory, so prune or use dynamic programming instead of naive brute force when the search space is large.
- The last line it prints must be `ANSWER: <value>`, where the value is a plain number or a fraction p/q at full precision. Do not round, even if the puzzle asks for a rounded answer.

Briefly describe your approach, then give the complete program.
