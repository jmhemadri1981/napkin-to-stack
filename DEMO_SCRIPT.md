# Demo video script: target 2:40 (hard limit is under 3:00)

**Setup before recording**

- Draw the diagram on a real whiteboard or paper with a marker. Use the sample's layout, and include the red "auth??" and "TODO: monitoring" notes.
- Take the photo with your phone at a slight angle. A real photo makes the point better than the generated sample.
- Run `before` and `after` once off-camera so model access and credentials are warmed up. Record the second run.
- Terminal font at 18pt or larger, with a split screen showing the terminal and `output/after/stack.ts`.

| Time | On screen | Say (roughly) |
|---|---|---|
| **0:00–0:15** | Phone photo of the whiteboard, full screen | "Every design review starts like this: boxes and arrows on a whiteboard. My architecture agent, ArchBuddy, can review a design and write CDK for it, but only if someone types the design out first. Nobody does." |
| **0:15–0:40** | Terminal: `python demo.py before whiteboard.jpg` | "Here's ArchBuddy before. It's a Strands agent on Bedrock with one tool, save_file. I give it the photo…" *(wait for the reply)* "…and it says it can't see images. That's honest, but it's a dead end." |
| **0:40–1:05** | `agent.py`: highlight `tools.append(read_whiteboard)`, then the tool docstring | "So I gave it one new tool: read_whiteboard. It's one import and one line in the tool list. Same model, same prompt, same everything else." |
| **1:05–1:30** | Simple diagram: photo → Rekognition + Bedrock → referee | "Inside, it uses two readers. Rekognition reads what's written, and Claude vision on Bedrock reads what it means. Then plain Python referees: every label must be backed by OCR evidence, arrows to nowhere get dropped, and text nobody explained gets flagged. A vision model can't just invent a Kinesis box." |
| **1:30–2:15** | Terminal: `python demo.py after whiteboard.jpg`, with the tool call visible | "Same prompt, after." *(Point at the tool call.)* "It found [N] components, each verified or flagged. It caught my 'auth??' note and recommends Cognito on API Gateway, a dead-letter queue on SQS, alarms for the TODO, and point-in-time recovery on DynamoDB." *(If anything is unverified:)* "And here it asks me to confirm a label it wasn't sure about, instead of guessing." |
| **2:15–2:35** | `output/after/stack.ts`: scroll, highlight `// TODO(suggested)` | "And it saved a CDK stack. Only what I actually drew becomes resources. Its suggestions stay as TODOs, so the design remains mine." |
| **2:35–2:45** | Side-by-side summary table (before/after) | "One tool took ArchBuddy from 'please describe it' to whiteboard-to-CDK in about [N] seconds. The two-readers-plus-referee pattern works for any agent that has to trust what it sees." |

**Recording tips**

- Use QuickTime or OBS and upload as unlisted or public on YouTube. The rules require a public link.
- Cut dead time while the model thinks. Keep the tool-call line on screen; that's your proof.
- Show the `[[...]]` numbers from your actual run, and use the same numbers in SUBMISSION.md.
