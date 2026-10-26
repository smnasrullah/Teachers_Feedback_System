# Question Bank (tumi pore fill korbe)

Tarpor Claude Code-e bolo: `Load docs/QUESTION_BANK.md into the question bank using the load_questions command.`

**Columns**
- Category: Teaching · Course Content · Lab · Assessment · Behaviour · Overall (notun category likhle auto toiri hobe)
- Type: `rating` (1-5 star) · `likert` · `choice` · `yesno` · `text`
- Required: `yes` / `no` (tumi bolechho shob question-er uttor dite hobe, tai default `yes`)
- Applies: `theory` · `lab` · `all`
- Options / বিকল্প: shudhu `choice` type-er jonno, `A / B / C` format-e (English ar Bangla alada column-e, sonkha mele). Onno type-e faka rakho.

**Example (ei code block parser porbe na, nijer question niche table-e likho)**
```
| 1 | Teaching | The teacher explains concepts clearly. | শিক্ষক বিষয়বস্তু স্পষ্টভাবে বোঝান। | rating | yes | all |  |  |
| 2 | Lab | Lab equipment was sufficient. | ল্যাবের সরঞ্জাম যথেষ্ট ছিল। | choice | yes | lab | Yes / Partly / No | হ্যাঁ / আংশিক / না |
```

| # | Category | Question (English) | প্রশ্ন (বাংলা) | Type | Required | Applies | Options (EN) | বিকল্প (বাংলা) |
|---|---|---|---|---|---|---|---|---|
| 1 |  |  |  |  |  |  |  |  |
| 2 |  |  |  |  |  |  |  |  |
| 3 |  |  |  |  |  |  |  |  |

## Rating topics (kon kon bisoye rating hobe)
- (pore likho, ekta line-e ekta topic, jemon: Course Content, Teaching Quality, Punctuality, Lab Support)
