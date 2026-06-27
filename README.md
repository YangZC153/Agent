Adapted from genggng, with thanks to the original author and the Hermes Agent project; this fork focuses on frontier generative recommender systems.

## Daily Investment Advice

The arXiv daily pipeline now emits a second investment-advice message after the paper report. It is suggestion-only and never performs real trades.

In the Hermes no-agent cron path, `DAILY_RUN_DIRECT_SEND=1` makes `daily_run.py` send the paper report and investment advice as two separate Feishu messages via `hermes send`, then print `[SILENT]` so cron does not merge them into one stdout delivery.

Run it independently with:

```bash
python3 -m investment_advice.dca
```

The public output is limited to:

```text
股市指数：上一交易日（YYYY-MM-DD）xxxx.xx，最新交易日（YYYY-MM-DD）xxxx.xx
涨跌比例：上涨/下跌x.xx%
推荐投资金额：xxx 元
推荐原因说明：xxxxxxxx
```

Runtime state is stored in `investment_advice/investment_state.json` and ignored by git. Internal URLs and calculation details stay in config/logs and must not be shown in the public Feishu message.
Investment advice is Feishu-only and must not be written to `viewer/papers_data.json` or GitHub Pages.
