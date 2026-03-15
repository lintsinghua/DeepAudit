"""
智能合约拒绝服务攻击漏洞知识
"""

from ..base import KnowledgeDocument, KnowledgeCategory

DENIAL_OF_SERVICE = KnowledgeDocument(
    id="vuln_denial_of_service",
    title="Denial of Service (DoS) Attacks",
    category=KnowledgeCategory.VULNERABILITY,
    tags=["dos", "gas-exhaustion"],
    severity="high",
    cwe_ids=["CWE-400"],
    owasp_ids=["SC10:2025"],
    content="""
智能合约中的拒绝服务（DoS）攻击涉及利用漏洞耗尽 Gas、CPU 周期或存储等资源，使智能合约变得不可用。常见的类型包括：恶意行为者创建需要过多 Gas 的交易从而导致 Gas 耗尽攻击、利用区块 Gas 限制阻碍合法交易，以及利用合约调用序列获取未授权资金的可重入攻击。这种攻击会耗尽合约资源，使其无法正常发挥功能。

## 危险模式

### 依赖容易失败的外部调用
当合约状态的推进依赖于向外部不受信任的地址发送以太币时，恶意地址可以故意拒绝接收转账，从而卡死整个合约流程。

```solidity
# 危险 - 如果前任国王的地址是一个包含 revert 逻辑的恶意回退函数，它将阻止新国王认领王位，导致拒绝服务
contract Solidity_DOS {
    address public king;
    uint256 public balance;

    function claimThrone() external payable {
        require(msg.value > balance, "Need to pay more to become the king"); //

        //If the current king has a malicious fallback function that reverts, it will prevent the new king from claiming the throne, causing a Denial of Service.
        (bool sent,) = king.call{value: balance}(""); //
        require(sent, "Failed to send Ether"); //

        balance = msg.value; //
        king = msg.sender; //
    }
}
```

## 攻击方式与影响
1. 成功的 DoS 攻击会使智能合约变得无响应，阻止用户按预期与其交互。这会破坏依赖该合约的关键操作和服务。
它可以导致财务损失，特别是在智能合约管理资金或资产的去中心化应用（dApps）中。
2. DoS 攻击会损害智能合约及其相关平台的声誉。用户可能会对平台的安全性和可靠性失去信任，从而导致用户流失和商业机会丧失。

## 检测要点
1. 检查合约逻辑是否依赖于具有不可控风险的外部调用（如 call）的成功才能继续执行后续的状态变更。
2.检查循环、遍历以及外部调用的使用情况，评估它们是否可能导致过度的 Gas 消耗或意外的成本。
3. 检查合约权限设计，确认是否过度授权给单一角色，这可能在私钥泄露时导致权限丧失或服务瘫痪。

## 安全实践
1. 确保智能合约能够处理持续的失败情况，例如通过采用“拉取而非推送（Pull over Push）”模式或对可能失败的外部调用进行异步处理，以维护合约的完整性并防止意外行为。
2. 在使用 call 进行外部调用、循环和遍历时要非常谨慎，以避免由于消耗过多 Gas 而导致交易失败。
3. 避免在合约权限中对单一角色进行过度授权。相反，应合理划分权限，并对具有关键权限的角色使用多重签名钱包管理，以防止因私钥泄露而失去权限。

修复示例
```solidity
# 安全 - 在转账前更新状态（检查-生效-交互模式），并使用 transfer 限制 gas 以防止恶意 fallback 函数攻击
contract Solidity_DOS {
    address public king;
    uint256 public balance;

    // Use a safer approach to transfer funds, like transfer, which has a fixed gas stipend.
    // This avoids using call and prevents issues with malicious fallback functions.
    function claimThrone() external payable {
        require(msg.value > balance, "Need to pay more to become the king"); //

        address previousKing = king; //
        uint256 previousBalance = balance; //

        // Update the state before transferring Ether to prevent reentrancy issues.
        king = msg.sender; //
        balance = msg.value; //

        // Use transfer instead of call to ensure the transaction doesn't fail due to a malicious fallback.
        payable(previousKing).transfer(previousBalance); //
    }
}
```

"""
)
