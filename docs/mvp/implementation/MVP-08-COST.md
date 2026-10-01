# MVP-08 cost forecast preparation

The checked-in [forecast input template](../../../config/cost_forecast.example.json)
lists every recurring category that must be priced before deployment. Copy it to an
ignored private location, set the intended region and price-verification date, replace
every `null` price and quantity with a checked value, and add line items when the
selected architecture incurs other charges. A zero is valid only when the service
truly has no charge in the selected account and scenario. Run:

```bash
python scripts/cost_forecast.py private_data/cost_forecast.json
```

The command refuses an incomplete scenario. It reports setup and recurring **gross**
costs against the $500 setup and configured monthly ceiling, plus the $50 recurring
target. Credits are reported separately; they never turn an over-budget gross plan
green. Development subscriptions are a separate tooling line. Estimate an idle, typical,
and busy month with separate private files, including any minimum charges. Revise the
quantities after the first-family measured run; keep the prices' verification date.

The current AWS pricing pages are the starting references for
[EC2](https://aws.amazon.com/ec2/pricing/on-demand/),
[EBS](https://aws.amazon.com/ebs/pricing/),
[S3](https://aws.amazon.com/s3/pricing/),
[Backup](https://aws.amazon.com/backup/pricing/),
[VPC addresses and transfer](https://aws.amazon.com/vpc/pricing/),
[Bedrock models and Managed KB](https://aws.amazon.com/bedrock/pricing/),
[Secrets Manager](https://aws.amazon.com/secrets-manager/pricing/),
[CloudWatch](https://aws.amazon.com/cloudwatch/pricing/), and
[Route 53](https://aws.amazon.com/route53/pricing/).
As of September 29, 2026, AWS lists Managed KB indexed storage at $5 per GB-month
of raw data and standard Retrieve calls at $1 per 1,000 calls; this is a component
rate, not a deployment quote. The intended account's region, credits, instance size,
curated index size, request counts, model route, backup size, and transfer are still
unverified. Do not apply infrastructure or run paid probes based on this template alone.

The calculator's synthetic tests cover missing cost categories, unpriced items,
duplicate names, invalid numbers, credit separation, and hard-ceiling failure. Live
08-C/E evidence must include the priced files' private location, region, date, cost
explorer or billing reference, application usage totals, and variance after use.
