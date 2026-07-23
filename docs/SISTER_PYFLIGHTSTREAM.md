# Sister library: pyflightstream

[pyflightstream](https://github.com/nevesgeovana/pyflightstream)
([PyPI](https://pypi.org/project/pyflightstream/)) is this project's
sister library by the same author: a version-aware, didactic Python
driver for the FlightStream panel-method solver. It builds native
solver scripts validated against an evidence-backed per-version
command database, executes them headlessly, parses the outputs, and
manages campaigns with a run manifest as the single identity
authority. The two libraries are co-developed as consciously
integrated projects (DD-22 and DD-23 here; AD-07 in the
pyflightstream SRS).

## The division of labor

| Concern | Home |
|---|---|
| Generic engineering data management: labeled datasets, provenance graphs, uncertainty propagation, publication plotting | ITACA |
| Driving FlightStream: version-aware command emission, execution, campaign management, run provenance | pyflightstream |
| Solver-specific knowledge (command database, probe evidence, physics regression) | pyflightstream, always |
| The adapter between the two | pyflightstream, behind a future optional extra |

ITACA is solver-agnostic (NREQ-10, DD-22) and never imports
pyflightstream. The driver's planned exporter will map its run
manifest, solver settings snapshot, and parsed result tables into
ITACA datasets through the public `itc.load` surface and the export
formats, so campaign outputs arrive here with their provenance
already attached.

## The cross-requirement convention

Each library may generate requirements for the other:

* A need pyflightstream's exporter cannot satisfy with the existing
  ITACA surface enters this repository as a candidate requirement
  carrying a pyflightstream origin, through the normal SRS process.
* An ITACA requirement may cite pyflightstream as its consumer;
  driver-side needs that are really generic data management migrate
  here instead of growing a second framework there.
* The driver's pandas and xarray usage migrates to ITACA per
  structure as capabilities land here (labeled axes gate that side);
  each migration is an evidenced change in the driver's repository.

## Shared process

Both repositories follow the same role-based review process (five
reviewer charters in `.claude/agents/` and the `role-review` skill;
DD-23) and equivalent documentation-currency discipline, with the
author holding the non-delegable seats in both.
