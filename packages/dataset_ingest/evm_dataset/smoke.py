"""A tiny synthetic dataset used to exercise the pipeline end to end.

**These records are synthetic and their labels are heuristic.** They are
not benchmark ground truth, they are not derived from any real
vulnerability, and nothing produced from them may be quoted as an
accuracy figure. They exist so that the ingestion pipeline - hashing,
family grouping, splitting, manifest building and the promotion gate -
can be exercised offline, with no network access and no dataset fetch.

The set is deliberately shaped to cover the failure modes the pipeline
exists to prevent:

* a reviewed vulnerable contract and a reviewed benign contract, so the
  promotion gate has something it *can* promote;
* a heuristic vulnerable contract, so the gate has something it must
  refuse;
* an unlabelled contract whose label is ``not-yet-determined``, which
  must never become a negative;
* two records of one family, which must land in the same split;
* a near-duplicate of the first record, which must be detected by the
  near-duplicate tier rather than by the exact or normalised tiers.
"""

from __future__ import annotations

from typing import Final

from .records import DatasetRecord

__all__ = ["SMOKE_RECORDS", "smoke_records"]


_REVIEWED_VULNERABLE = """// SPDX-License-Identifier: Apache-2.0
pragma solidity ^0.8.20;

contract Vault {
    mapping(address => uint256) public balances;

    function withdraw(uint256 amount) external {
        require(balances[msg.sender] >= amount, "insufficient");
        balances[msg.sender] -= amount;
        (bool ok, ) = msg.sender.call{value: amount}("");
        require(ok, "transfer failed");
    }
}
"""

_HEURISTIC_VULNERABLE = """pragma solidity ^0.8.20;

contract Pool {
    mapping(address => uint256) public shares;
    uint256 public totalShares;

    function deposit(uint256 amount) external {
        shares[msg.sender] += amount;
        totalShares += amount;
    }

    function getShare(address account) public view returns (uint256) {
        return shares[account];
    }
}
"""

_UNLABELLED = """pragma solidity ^0.8.20;

contract Staking {
    address public owner;

    constructor() {
        owner = msg.sender;
    }

    function stake(uint256 amount) external {
        require(msg.sender != address(0), "zero sender");
    }
}
"""

_FAMILY_FIRST = """pragma solidity ^0.8.20;

contract Bridge {
    mapping(address => uint256) public balances;
    address public owner;

    function deposit(uint256 amount) external {
        require(amount > 0, "zero amount");
        balances[msg.sender] += amount;
    }

    function ownerBalance() public view returns (uint256) {
        return balances[owner];
    }
}
"""

_FAMILY_SECOND = """pragma solidity ^0.8.20;

// A sibling contract in the same protocol family: different source and
// different logic, but the same protocol and the same bug class, so it
// must share a family key with the record above - and therefore share a
// split with it.
contract BridgeProxy {
    mapping(address => uint256) public pending;
    address public operator;

    function queue(uint256 amount) external {
        require(amount > 0, "zero amount");
        pending[msg.sender] = amount;
    }

    function flush(address account) external {
        require(msg.sender == operator, "not operator");
        pending[account] = 0;
    }
}
"""

_NEAR_DUPLICATE = """pragma solidity ^0.8.20;

// Same contract as the first record, with the variables renamed and the
// comments removed. The exact and the normalised hash both differ; only
// the near-duplicate tier must catch it.
contract Vault {
    mapping(address => uint256) public ledger;

    function withdraw(uint256 amount) external {
        require(ledger[msg.sender] >= amount, "insufficient");
        ledger[msg.sender] -= amount;
        (bool ok, ) = msg.sender.call{value: amount}("");
        require(ok, "transfer failed");
    }
}
"""

_REVIEWED_BENIGN = """pragma solidity ^0.8.20;

contract Escrow {
    address public payer;
    address public payee;
    uint256 public amount;
    bool public released;

    function deposit() external payable {
        require(msg.value > 0, "no value");
        payer = msg.sender;
        amount = msg.value;
    }

    function release() external {
        require(msg.sender == payee, "not payee");
        released = true;
    }
}
"""


#: The synthetic smoke dataset, in a fixed order.
SMOKE_RECORDS: Final[tuple[DatasetRecord, ...]] = (
    DatasetRecord(
        record_id="smoke-001",
        source_dataset="smoke",
        source_ref="smoke/contracts/Vault.sol",
        code=_REVIEWED_VULNERABLE,
        project="acme-vault",
        contract_name="Vault",
        chain="ethereum",
        compiler_version="0.8.20",
        swc_id="SWC-107",
        cwe_id="CWE-710",
        label="true",
        label_provenance="reviewed",
        severity="high",
        license="Apache-2.0",
    ),
    DatasetRecord(
        record_id="smoke-002",
        source_dataset="smoke",
        source_ref="smoke/contracts/Pool.sol",
        code=_HEURISTIC_VULNERABLE,
        project="beta-pool",
        contract_name="Pool",
        chain="ethereum",
        compiler_version="0.8.20",
        swc_id="SWC-101",
        label="true",
        label_provenance="heuristic-rule:unchecked-lowlevel-call",
        severity="medium",
        license="Apache-2.0",
    ),
    DatasetRecord(
        record_id="smoke-003",
        source_dataset="smoke",
        source_ref="smoke/contracts/Staking.sol",
        code=_UNLABELLED,
        project="gamma-staking",
        contract_name="Staking",
        chain="ethereum",
        compiler_version="0.8.20",
        swc_id="SWC-105",
        label="not-yet-determined",
        label_provenance="reviewed",
        license="Apache-2.0",
    ),
    DatasetRecord(
        record_id="smoke-004",
        source_dataset="smoke",
        source_ref="smoke/contracts/Bridge.sol",
        code=_FAMILY_FIRST,
        project="delta-bridge",
        contract_name="Bridge",
        chain="ethereum",
        compiler_version="0.8.20",
        swc_id="SWC-105",
        label="true",
        label_provenance="reviewed",
        severity="medium",
        license="Apache-2.0",
    ),
    DatasetRecord(
        record_id="smoke-005",
        source_dataset="smoke",
        source_ref="smoke/contracts/BridgeProxy.sol",
        code=_FAMILY_SECOND,
        project="delta-bridge",
        contract_name="BridgeProxy",
        chain="ethereum",
        compiler_version="0.8.20",
        swc_id="SWC-105",
        label="true",
        label_provenance="reviewed",
        severity="medium",
        license="Apache-2.0",
    ),
    DatasetRecord(
        record_id="smoke-006",
        source_dataset="smoke",
        source_ref="smoke/contracts/VaultRenamed.sol",
        code=_NEAR_DUPLICATE,
        project="acme-vault",
        contract_name="Vault",
        chain="ethereum",
        compiler_version="0.8.20",
        swc_id="SWC-107",
        cwe_id="CWE-710",
        label="true",
        label_provenance="reviewed",
        severity="high",
        license="Apache-2.0",
    ),
    DatasetRecord(
        record_id="smoke-007",
        source_dataset="smoke",
        source_ref="smoke/contracts/Escrow.sol",
        code=_REVIEWED_BENIGN,
        project="epsilon-escrow",
        contract_name="Escrow",
        chain="ethereum",
        compiler_version="0.8.20",
        label="false",
        label_provenance="reviewed",
        license="Apache-2.0",
    ),
)


def smoke_records() -> list[DatasetRecord]:
    """Return a copy of the synthetic smoke dataset.

    The records are synthetic and their labels are heuristic or
    synthetic-reviewed, not benchmark ground truth.
    """
    return list(SMOKE_RECORDS)
