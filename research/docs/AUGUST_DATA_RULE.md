# Research operating rule: August data

## Active-data requirement

For new Shaurya alpha research, **use the available August data as the active
research dataset**.  Do not default to the January/February archive merely
because it offers a convenient historical split.

When a holdout is needed, split the available August sessions chronologically:
use earlier August data for discovery/selection and later August data for the
frozen evaluation.  Preserve actual bid/ask and delay assumptions.

Use January/February only when the user explicitly requests that archive, or
when August cannot support a clearly stated technical requirement.  In the
latter case, stop and explain the requirement before using another period.

This rule also does not authorize use of an incomplete or still-open current
trading session.  The user decides whether such data is valid.
