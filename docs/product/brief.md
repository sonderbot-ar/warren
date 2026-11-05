# Warren product brief: the questions a student asks

Status: Accepted (F1, nov.03.2026) · Owner sign-off: approved nov.03.2026, with the sorting rule · Owner: front-end team (Structure Guide Decision 13)

Since sign-off: v0.9.6 (backlog #140) answers questions 1 and 2, v0.9.8 (#144) question 5 (v0.9.16, #167, adds the range on shocked runs), and v0.9.9 (#141) question 8 and part of 7, so six questions work today, five in part and four not yet. The questions and answers below are unchanged; only their "Hoy" lines and section 5 move as the engine delivers.

> **What you are approving.** Fifteen questions a finance student would ask Warren, in Spanish, and what Warren answers to each. Questions come in four kinds: a reported figure (*dato*), a model estimate (*estimación*), a changed assumption (*cambio de supuesto*) and an event (*evento*). Warren shows how it read the question before computing anything. Changed assumptions are recomputed by tested code. Events are answered only with similar past cases, how many there are, and what to watch: never a number an AI made up. Warren never predicts prices or gives advice. Two questions work today, eight in part and five not yet; what is missing is eight requests to the engine team (section 5). Signing commits Warren's first screens to these questions. How questions are sorted was decided on its own card (an AI reader, built from the start). How screens look comes later, with mockups.

This brief says which questions Warren must answer for a finance student, how each kind is answered, and what the engine still needs. Engine design docs check their *Product impact* against it (`docs/team-sync.md`). Screens come later (F2, after M10); this brief decides what they must hold, not how they look.

## 1. Who asks, and in what language

- **The student.** An undergraduate or master's student in finance or business at a Latin American university, in or after a first corporate finance course: knows the three statements, DCF and WACC, and has built them in a spreadsheet.
- **The professor.** Sets a company and a date for the class, and wants to show where every number came from and what really happened afterwards. The owner wants both student and professor served (oct.30.2026).
- **Language.** Spanish first, with an English toggle (owner, oct.30.2026); the informal *tú*, chosen as a neutral form (Argentina and Uruguay use *vos*, Colombia often *usted*; a regional setting can change it later). Terms as Latin American courses use them: *ingresos* (or *ventas*), *margen operativo*, *flujo de caja libre*, *costo promedio ponderado de capital (WACC; CPPC en algunos cursos)*, *tasa libre de riesgo*, *prima de riesgo de mercado*, *valor intrínseco por acción*, *puntos básicos (pb)*, *fecha de corte* (as-of date), *rango p10–p90* glossed as "8 de cada 10 resultados deberían caer aquí". Money in *millones de US$*. Number format and spreadsheet formulas follow a **region** setting, apart from the language: Mexico and Central America write 1,234.5 and `=SUMA(A1,B1)`; most of South America writes 1.234,5 and `=SUMA(A1;B1)`. Filing names (10-K, 10-Q, XBRL tag) stay in English with a one-line gloss. Portuguese later (Decision 11). All reader-facing text lives apart from logic (Decision 11, guardrail 5).
- **Companies.** The Phase 1 universe only: Apple, Microsoft, Walmart, Coca-Cola, Procter & Gamble, Johnson & Johnson, Caterpillar, ExxonMobil (`domains/fundamentals/universe.csv`). US GAAP, US dollars. Exxon's filings in Warren stop in August 2026 because the company changed its legal entity (#126); every Exxon answer says so. Latin American companies under IFRS are Phase 2 (Decision 11).

## 2. How Warren sorts a question (backlog #130; goes to the owner)

Every question is read first, and the reading is shown to the student **before anything is computed**. The student can correct it.

| Kind (shown to the student) | #130 term | What it names | How Warren answers | Example |
|---|---|---|---|---|
| **Dato** | literal | A line item or ratio for a company and a reported period | The number as filed, with its filing, tag, period and filing date; flagged when a later filing changed it (#128) | "¿Cuánto vendió Apple el último trimestre?" |
| **Estimación** | literal | A model output for a company on a date: a forecast, a value, WACC, or the model's past forecasts against what happened | The engine's run as of that date, every assumption with its source, and the uncertainty the engine measures for that output | "¿Cuánto vale Microsoft por acción?" |
| **Cambio de supuesto** | literal | A model input and a new value, directly or through a listed transmission | Tested code recomputes with the input changed and shows before, after and the ripple | "¿Y si la Fed sube 25 pb por sorpresa?" |
| **Evento** | hypothetical | An event, past or future, that is not a model input and has no listed transmission | Similar past cases chosen by a rule, what followed against what Warren expected then, how many cases there are, how close each is, and the metrics to watch. **Never a number an AI made up** | "¿Y si los demócratas ganan las elecciones intermedias?" |

**The rule**, checked in this order. A question is a *cambio de supuesto* when every change it asks for is one of the model's inputs with a value, or reaches one through a transmission on the **list of transmissions**. A question that names an event, past or future, is an *evento*. A question with no change and no event is a *dato* when it names a filed line item or ratio, and an *estimación* when it names a model output (a forecast, a value, WACC, or the model's past forecasts).

- **Model inputs** (`domains/analysis/dcf.py`, `DRIVERS` and `SINGLE_VALUES`): revenue growth, operating margin, tax rate, depreciation and amortisation, capex, working capital (each as a share of revenue, by period); risk-free rate, beta, equity risk premium, cost of debt, the tax rate on interest, terminal growth, debt, cash, minority interest, shares. Two teaching overrides are inputs too: WACC set directly (it then bypasses its parts, and the reading says so) and the terminal value method (Warren's, or Gordon's for contrast). Never inputs: the market value of equity (it comes from the share price, and Warren never edits a price) and the roll-forward years (bookkeeping).
- **List of transmissions** (checked into the engine; adding one is an engine change with review and an owner card, because it is a new method under Decision 4). Proposed first and only entry: *an unexpected change in the Fed's policy rate → the 10-year Treasury yield*, Warren's risk-free rate, with a sourced range from the monetary-policy literature (Kuttner 2001; Gürkaynak, Sack & Swanson 2005). An expected move is already in the yield on the as-of date, so it changes nothing; the reading says so.
- So "¿y si el dólar se fortalece?" and "¿y si sube la inflación?" are *eventos* today: neither the exchange rate nor inflation is an input, and no transmission is listed for them.

**Ambiguous questions** are sorted *evento*, and the reading offers the *cambios de supuesto* the student may mean ("¿quieres bajar el margen operativo o el crecimiento de ingresos?"). Warren never quietly turns an event into an input.

**Who sorts.** Decided by the owner on nov.03.2026: the AI reader, built from the start, with menus only as a fallback when it is unsure or unavailable ("no menus first"; Decision 9). The two ways:

1. **An AI reader** (chosen). An AI model reads the question and returns only structured fields: the kind, the company, the date, and the inputs it names. A value is filled in only when it is copied word for word from the student's question, and code checks that it appears there; otherwise the field stays blank for the student to fill in. Code checks the rest against the input list and the transmission list; the student sees the reading as an editable card, confirms or fixes it, and only then does code compute. The AI's output is a label, never a financial number (standing rule). It is a new AI step, accepted by the owner and recorded in Decision 9 (nov.03.2026), and it is measured on a labelled set of student questions (these fifteen and more) before students use it.
2. **Menus only.** The student picks the kind, then the company, date and input from menus, and types the value. No AI, works with today's engine, and the reading card is the same. The cost: a student cannot simply type a question.

Either way the reading card is the same screen. F2 builds the reader with the first screens; the menus are its fallback, never the main way in.

**Point in time.** Every query behind an answer uses only what was public on the *fecha de corte*. The default is the last day that has ended in New York (the engine refuses a day still in progress). Asking about a past date is an explicit choice, and then what happened afterwards is shown beside the estimate (#128).

**Which uncertainty each answer shows.** Revenue and operating income forecasts: the p10–p90 range from Warren's own past misses (M9), with that company's measured coverage. Value per share: the values at the equity risk premium ± one standard error, labelled "sensibilidad a la prima de riesgo, no un rango de resultados", and, when news shocks are applied, the simulation's p10–p90. WACC, cost of equity and beta: point values, labelled as estimates with their method, and the cost of equity also at the risk premium ± one standard error. A reported figure: none, but a flag when it was revised. An event: the number of cases and the thin-evidence flag.

## 3. The questions

Fifteen questions, written as a student would ask them, with an English gloss. "Hoy" (today) says whether the engine answers it now: **Sí** (an engine command answers it; the app only needs to call it), **En parte** (the data exists but not the query or the output), or **No**. Each gap links to its engine request (section 5).

### Datos: what the filings say

**1. ¿Cuánto vendió Apple en su último trimestre y de qué reporte sale ese número?**
*How much did Apple sell last quarter, and which filing does that number come from?*
- Kind: Dato.
- Returns: revenue for the last reported quarter, its 10-Q or 10-K (accession), the XBRL tag, the period end and the filing date; the first-reported and the latest figure, flagged when they differ (the engine knows *that* it changed, not *why*). Apple's fiscal fourth quarter has no 10-Q: it is the year in the 10-K minus the first nine months, and is marked as derived.
- Hoy: **Sí** (since v0.9.6): `python -m domains.analysis reported --ticker AAPL --period latest-quarter --as-of <fecha> --json`, or the call `domains.analysis.reported.reported_period`. Returns the filing (form, accession, date, EDGAR link), first-reported and latest with `changed`, and the derived fiscal Q4 with its inputs. Request R1 (#140), done.

**2. ¿Cómo ha cambiado el margen operativo de Coca-Cola en los últimos cinco años frente al de Procter & Gamble?**
*How has Coca-Cola's operating margin changed over five years compared with P&G's?*
- Kind: Dato (two companies, a ratio).
- Returns: operating margin by fiscal year for both, as reported (one-off charges included, and said so), each year traced to its filing, the formula, and the fiscal-year ends side by side (Coca-Cola: December; P&G: June, so the "same" year is six months apart).
- Hoy: **Sí** (since v0.9.6): the `reported` command once per fiscal year and company (`operating_margin`, with its formula, the lines it uses and their filings; fiscal-year labels are each company's own). The app asks five periods per company, and builds the spreadsheet formula a student would type from `uses` (design principle 5); it never computes the ratio. Request R1 (#140), done.

### Estimaciones: what the model says

**3. ¿Cuánto vale Microsoft por acción según un DCF, y qué supuestos usa?**
*What is Microsoft worth per share on a DCF, and what assumptions does it use?*
- Kind: Estimación.
- Returns: value per share with its values at the equity risk premium ± one standard error; the five-year drivers; WACC; the terminal value method; every assumption with its source. The market price appears only as an input to the capital weights, never as a target.
- Hoy: **Sí**: `python -m domains.analysis dcf --ticker MSFT` (no AI, free). Without `--as-of` it uses the last day that has ended in New York and says so, with the date of the last EDGAR download (since v0.9.7, #128). A past date is asked with `--as-of <fecha>`; the full run (`python main.py run`) then also shows the forecast against what was reported afterwards.

**4. ¿Cuál es el WACC de Walmart y de dónde sale cada parte?**
*What is Walmart's WACC, and where does each part come from?*
- Kind: Estimación.
- Returns: risk-free rate (10-year Treasury, FRED DGS10, its date), beta (method and window), equity risk premium (realised S&P 500 over 10-year bonds since 1989, with its standard error), cost of debt, the weights and the formula. It says that debt is weighted at book value, where textbooks prefer market value.
- Hoy: **Sí** (the run report's "Cost of capital" section).

**5. ¿Cuánto venderá Apple en los próximos cuatro trimestres, y qué tan seguro es ese pronóstico?**
*How much will Apple sell in the next four quarters, and how sure is that forecast?*
- Kind: Estimación.
- Returns: the baseline revenue path, quarter by quarter, with its p10–p90 range from Warren's own past misses known on that date (M9), and how often such ranges held: across all companies 83% (a p10–p90 range should hold about 8 times in 10), and Apple's own figure beside it, since coverage differs by company (4 of the 8 companies fell outside 65–95%, the band the team set as acceptable for an 80% range; v0.9). So the screen says plainly when Apple's own ranges held less or more often than the pooled 83%.
- Hoy: **Sí** for the baseline's range (v0.9.8, #144): any run gets its p10–p90 per quarter, how often such ranges held across all companies and for the company, and a coded verdict against 65–95%. On a pipeline run with shocks, the range on top of each simulation (v0.9.16, #167: `run_ranges(conn, run_id, sim_id=S)` or `ranges run --sim-id S`; show `*_center` as the forecast, label `coverage_is_baseline`), and the pipeline report's section 7. Which simulation goes with a variant waits for #201.

**6. ¿Qué tan bien ha pronosticado Warren a Procter & Gamble en el pasado?**
*How well has Warren forecast P&G in the past?*
- Kind: Estimación (the model's track record).
- Returns: past forecasts beside the first-reported actuals, quarter by quarter, the error, how often the range held the actual, and the same for a simple benchmark (last year's quarter carried forward), for that company. Where the range did not hold for this company, it says so.
- Hoy: **Sí** (since v0.9.14, #145; monthly history since 2019; the case batches join when M10 merges, #189): `python -m domains.evaluation track-record --ticker PG --json`, or the call `domains.evaluation.track_record.track_record`. Each past forecast quarter with the first-reported actual, the miss, the benchmark's miss and whether the range held; per item and horizon a coded verdict against the benchmark and the range's record beside the other companies'. Lead with the `headline` cell.

### Cambios de supuesto: change an input, see the ripple

**7. ¿Qué le pasa al WACC y al valor de Caterpillar si la Fed sube la tasa 25 puntos básicos por sorpresa?**
*What happens to Caterpillar's WACC and value if the Fed unexpectedly raises rates by 25 bps?*
- Kind: Cambio de supuesto, through the listed transmission.
- Reading shown first: "Cambio: tasa libre de riesgo, por una subida inesperada de la Fed. Traslado a la tasa a 10 años: entre A y B pb por cada 25 pb (fuente). Si la subida ya se esperaba, la tasa de hoy ya la incluye y no cambia nada." A and B come from the engine's sourced range (R2c), never from the app.
- Returns: before and after for the risk-free rate, cost of equity, WACC, terminal growth and value per share, at the low and the high end of the transmission range, with the reason for each move. It names the run's terminal value method and what follows from it. Two of Warren's own choices, not general rules, shape the answer, and the screen says so: terminal growth is set equal to the risk-free rate (the usual ceiling, Damodaran), and new investment after year five earns exactly its cost of capital (RONIC = WACC: the return on new invested capital equals its cost, so growth adds no value), which makes terminal value NOPAT × (1 + g) ÷ WACC. So growth moves with the rate but barely matters, and the higher cost of equity, hence WACC, drives the change. The cost of debt does not move: Warren takes it from past interest over average debt.
- Hoy: **En parte** (since v0.9.9, #141): `python -m domains.analysis whatif --run-id R --add risk_free=0.0025 --json` (or `domains.analysis.whatif.revalue`) moves the risk-free rate and shows cost of equity, WACC and value per share before and after, with terminal growth and the growth fade following it and each moved line's cause. The app must label it "if the 10-year yield moved by 25 bp": the Fed's surprise to the 10-year transmission, with its low and high ends, is R2c (#143).

**8. Si el margen operativo de Walmart baja un punto porcentual, ¿cuánto cambia su valor por acción?**
*If Walmart's operating margin falls by one percentage point, how much does its value per share change?*
- Kind: Cambio de supuesto.
- Returns: before and after value per share, the free cash flow path both ways, and the ripple: operating income, taxes, free cash flow, terminal value.
- Hoy: **Sí** (since v0.9.9): `python -m domains.analysis whatif --run-id R --add operating_margin=-0.01 --json`, or the call `domains.analysis.whatif.revalue`. Stores a linked what-if run that reproduces to the cent and returns before, after and change for revenue, EBIT, operating taxes, NOPAT and FCFF per period, the terminal value, the bridge to equity and value per share, each with the inputs behind the move. Request R2a (#141), done.

**9. ¿Qué tan sensible es el valor de Coca-Cola al WACC y al crecimiento terminal?**
*How sensitive is Coca-Cola's value to WACC and terminal growth?*
- Kind: Cambio de supuesto (two inputs over a grid).
- Returns: value per share over a grid of WACC (set directly, a teaching override) and terminal growth, with the run's own point marked. The lesson the screen states: under Warren's terminal method the table is almost flat along growth and steep along WACC, unlike the textbook Gordon model, which is shown beside it for contrast. Cells where growth reaches WACC say "no definido: el crecimiento terminal alcanza el WACC", never zero, under both methods: Warren's short formula comes from the same perpetuity as Gordon's, and that perpetuity has a value only while growth stays below WACC (v0.5.4).
- Hoy: **Sí** (v0.9.12, #142: `sensitivity.grid`; Gordon is steeper on both axes, so the screen states how much growth moves value compared with WACC, which the engine's verdict gives; a cell at WACC ≤ 0 says "no definido: el WACC es cero o menor").

### Eventos: answered from past cases

Every event answer shows, for each case: the company and date with its source, whether it is the same company and the same mechanism as the question, what Warren forecast just before, what was reported after, and that miss beside Warren's usual miss for that company on quarters without an event, so a normal error is not read as the event's effect. It always shows the number of cases (n) and a thin-evidence flag when n is small. Cases are chosen by a stated rule (event type and tags), not by hand.

**10. ¿Qué pasó con los ingresos y márgenes de Microsoft después de comprar Activision Blizzard?**
*What happened to Microsoft's revenue and margins after it bought Activision Blizzard?*
- Kind: Evento (a past event).
- Returns: the case (Microsoft, 13 October 2023), what Warren forecast before, the four quarters reported after, and the warning that the acquisition changed the company's scope: most of the gap is Activision's revenue being added, not a forecast miss (the backtest leaves such quarters out). Also: Warren's AI news shocks have mis-sized mergers so far (`docs/phase1-review.md`).
- Hoy: **En parte**. Cases, runs and scores are stored; no query. Request R5 (#146).

**11. ¿Qué le pasaría a Coca-Cola si el dólar se fortalece frente a las monedas de América Latina?**
*What would happen to Coca-Cola if the dollar strengthens against Latin American currencies?*
- Kind: Evento (the exchange rate is not an input and has no listed transmission).
- Returns: today the library has one currency case, and it is another company (Microsoft cut its guidance for currency in June 2022: same mechanism, different company), so the answer is n = 1, thin evidence. Then the metrics to watch (share of revenue outside the US, the currency note in the 10-K), and the *cambio de supuesto* the student may mean: lower revenue growth.
- Hoy: **No**. The nearest case is stored, but choosing cases by rule needs the theme tags of R6 (it is filed as a guidance case, not a currency case). Requests R5, R6 (#146, #147).

**12. Si Apple vuelve a tener problemas de producción en China como en 2022, ¿cuánto bajarían sus ventas?**
*If Apple has production problems in China again, as in 2022, how much would its sales fall?*
- Kind: Evento (it asks for a number, but names an event).
- Returns: the two Apple cases (February 2020 and November 2022, same company; the 2022 case is the same mechanism, the 2020 case is close, as it mixed supply problems with lower demand): what Warren expected then, what was reported, the gap by quarter beside Apple's usual miss. It says plainly that these are past outcomes, not a forecast, and that two cases are thin evidence.
- Hoy: **En parte** (the cases and their scores are stored). Request R5 (#146).

**13. ¿Qué le pasa a Johnson & Johnson si los demócratas ganan las elecciones intermedias en Estados Unidos?**
*What happens to J&J if the Democrats win the US midterm elections?*
- Kind: Evento (the owner's example in #130).
- Returns: "No hay casos parecidos en la biblioteca" first, n = 0. Then only the metrics to watch (US share of pharmaceutical sales, drug-pricing risk in the 10-K's risk factors). No number, and no weak analogy dressed up as a close one.
- Hoy: **No**. There is no election or policy case yet. Requests R5, R6 (#146, #147).

**14. ¿Qué le pasa a ExxonMobil si la OPEP recorta su producción?**
*What happens to ExxonMobil if OPEC cuts production?*
- Kind: Evento.
- Returns: the nearest case (March 2020, the oil price war, marked "dirección opuesta": supply rose and prices fell) and what followed; the metrics to watch (realised oil price, upstream earnings); and that Exxon's filings in Warren stop in August 2026 (#126).
- Hoy: **No**. The nearest case is stored, but choosing it by rule needs R6's tags. Requests R5, R6 (#146, #147), and #126.

**15. ¿Qué le pasa a Walmart si sube la inflación?**
*What happens to Walmart if inflation rises?*
- Kind: Evento, ambiguous (tests the rule's edge: inflation is not an input and has no listed transmission).
- Reading shown first: "Lo leo como un evento (inflación más alta), no como un cambio de supuesto." Then the nearest case (July 2022, Walmart cut its profit outlook as inflation pushed shoppers to groceries: same company, same mechanism, n = 1) and what followed; and two *cambios de supuesto* to choose from: lower operating margin, or different revenue growth.
- Hoy: **No**. The nearest case is stored, but choosing cases by rule needs the theme tags of R6 (it is filed as a guidance case, not an inflation case). Requests R5, R6 (#146, #147).

## 4. Out of scope, and how Warren says so

- **Prices and "is it cheap?".** "¿Va a subir la acción de Apple?", "¿Está cara o barata?" Warren never predicts prices or gives advice (owner, oct.14.2026). It answers: "Warren no pronostica precios ni dice si comprar. Te muestro su valor intrínseco, su rango y de qué supuestos depende."
- **Other companies.** "¿Cuánto vale Mercado Libre?" Not in the universe yet. It lists the eight companies and says Latin American companies under IFRS are planned.
- **Today's news as a number.** "¿Cuánto le afecta la noticia de hoy?" Answered as an *evento* (past cases), never as an AI estimate.
- **Concepts** ("¿qué es la deuda neta?") are answered in the side panel's *Concepto* tab of the number they belong to (design principles), not as questions of their own.

## 5. What this brief asks of the engine

Each is an issue labelled `backlog` and `front-end` (`docs/team-sync.md`, rule 4). The engine team weighs them with its backlog. F2's first screen needs R1 (done in v0.9.6) and #128 (done in v0.9.7); the rest serve later screens.

| Id | Ask | Questions | Size (engine lead) | Issue |
|---|---|---|---|---|
| R1 | Reported figures and named ratios for a company and period, with provenance, first reported and latest, revision flag (takes over #128 item 2) | 1, 2 | M | #140 (done, v0.9.6) |
| R1b | Net margin on net income to the parent (left out of #140; no brief question needs it yet) | — | — | #157 |
| R2a | What-if revaluation: a stored run revalued with named inputs changed, deterministic, stored as a linked child run that reproduces to the cent | 7, 8 | L | #141 (done, v0.9.9; debt #170, WACC and terminal method #171) |
| R2b | Two-input sensitivity grid on R2a | 9 | S | #142 (done, v0.9.12) |
| R2c | The list of transmissions, starting with an unexpected policy-rate move → 10-year yield, as a sourced range (owner card: a new method) | 7 | M | #143 |
| R3 | Error ranges (M9) and the company's own coverage on every run | 5 | S–M | #144 |
| R4 | Track record per company from the stored batches | 6 | S | #145 (done, v0.9.14) |
| R5 | Past-event query: cases by rule, closeness, n and a thin-evidence flag, the usual-miss comparison, scope-change warning, and a sourced "metrics to watch" table | 10–15 | M | #146 |
| R6 | Analogue cases for currency, inflation, commodity supply and elections, in a separate, unscored file | 11, 13, 14, 15 | M | #147 |
| — | Runs default to the latest ended day; a past date shows what was reported afterwards | 3, 5 | | #128 (done, v0.9.7) |
| — | The sorting rule and the AI reader (owner decision) | all | | #130 |
