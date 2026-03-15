"""
智能合约时间漏洞知识
"""

from ..base import KnowledgeDocument, KnowledgeCategory

FRONT_RUNNING = KnowledgeDocument(
    id="vuln_front_running",
    title="Front-running Attacks",
    category=KnowledgeCategory.VULNERABILITY,
    tags=["front-running", "mempool", "mev"],
    severity="high",
    cwe_ids=["CWE-362"],
    owasp_ids=["SC05:2023"],
    content="""
抢跑攻击（Front-running）是一种恶意行为者利用对网络中未决交易（pending transactions）的了解来获取不公平优势的攻击方式。这在去中心化金融（DeFi）生态系统中尤为普遍。攻击者通过观察内存池（mempool，即未决交易列表），并策略性地利用更高的 Gas 费用放置自己的交易，以确保他们的交易在目标交易之前被处理。这不仅会导致目标用户面临潜在的财务损失，还会破坏智能合约的预期功能。

## 危险模式

### 缺乏滑点保护的代币兑换
当用户发起兑换时，如果未设置最小预期获得量（缺乏滑点检查），则极易被抢跑者利用。
```solidity
# 危险 - 缺乏适当的滑点检查（期望输出设置为0），容易受到抢跑攻击
contract VulnerableSwap {
    address public pancakeRouter;
    address public ssToken;

    constructor(address _pancakeRouter, address _ssToken) {
        pancakeRouter = _pancakeRouter;
        ssToken = _ssToken;
    }

    function swapBNBForSSToken(uint256 amount) private {
        address[] memory path = new address[](2);
        path[0] = IPancakeRouter02(pancakeRouter).WETH();
        path[1] = ssToken;

        IPancakeRouter02(pancakeRouter).swapExactETHForTokensSupportingFeeOnTransferTokens{
            value: amount
        }(0, path, address(this), block.timestamp);
    }
}
```
## 攻击方式与影响
1. 攻击者观察到一笔大额的兑换交易，并插入他们自己的具有更高 Gas 费用的交易，使其优先被处理。
2. 抢跑者通过在其他人之前执行大额交易，可以人为地抬高或压低代币价格。
3. 由于被操纵的交易顺序，受害者最终可能会为代币支付更多的费用，或者获得的代币远少于预期。

## 检测要点
1. 审查与去中心化交易所（如 PancakeSwap, Uniswap）交互的兑换逻辑，检查是否将 amountOutMin （最小输出量）硬编码为 0。
2. 检查对交易顺序敏感的业务逻辑，评估其是否直接暴露在内存池中而未采用保护机制（如两步提交）。

## 安全实践
1. 根据网络费用和兑换规模，实施 0.1% 到 5% 之间的滑点限制，以防范抢跑者利用更高的滑点率。
2. 使用两步流程（Two-step process），即用户在不透露详细信息的情况下提交操作（Commit），然后在稍后公开确切信息（Reveal），这使得攻击者更难预测和利用交易。
3. 将多个交易捆绑在一起并作为一个单元处理，使攻击者难以挑出并利用单个交易。
4. 持续监视可能利用抢跑机会的自动化机器人和脚本，以帮助早期检测和缓解。

修复示例
```solidity
# 安全 - 引入滑点限制参数 (amountOutMin) 保护交易
contract SafeSwap {
    // ... 状态变量 ...

    // 要求调用者（或前端界面）传入计算好的最小可接受代币数量作为滑点限制
    function swapBNBForSSToken(uint256 amount, uint256 amountOutMin) private {
        address[] memory path = new address[](2);
        path[0] = IPancakeRouter02(pancakeRouter).WETH();
        path[1] = ssToken;

        // 实施滑点限制：如果由于抢跑导致实际获得的代币少于 amountOutMin，交易将安全回滚
        IPancakeRouter02(pancakeRouter).swapExactETHForTokensSupportingFeeOnTransferTokens{
            value: amount
        }(amountOutMin, path, address(this), block.timestamp);
    }
}
```

""",
)

TIMESTAMP_DEPENDENCE = KnowledgeDocument(
    id="vuln_timestamp_dependence",
    title="Timestamp Dependence",
    category=KnowledgeCategory.VULNERABILITY,
    tags=["timestamp", "block"],
    severity="medium",
    cwe_ids=["CWE-384"],
    owasp_ids=["SC03:2023"],
    content="""
以太坊上的智能合约通常依赖 `block.timestamp` 来执行对时间敏感的功能，例如拍卖、彩票和代币归属。然而，`block.timestamp` 并不是完全不可变的，因为挖出该区块的矿工可以在以太坊协议实现允许的约 15 秒窗口内对其进行轻微调整。这产生了一个漏洞，矿工可以为了自己的利益操纵时间戳。
例如，在一个去中心化拍卖中，如果矿工同时也是出价人，他们可以通过修改时间戳来在自己是最高出价人时提前结束拍卖，从而获得不公平的胜利。

## 危险模式

### 依赖时间戳决定关键逻辑或随机结果
将 `block.timestamp` 用作随机数生成的熵源或用作非常严格的条件限制是非常危险的。
```solidity
# 危险 - 使用区块时间戳的最后一位数字来决定输赢
contract DiceRoll {
    uint256 public lastBlockTime;

    constructor() payable {}

    function rollDice() external payable {
        require(msg.value == 5 ether, "Must send 5 ether to play"); // Player must send 5 ether to play
        require(block.timestamp != lastBlockTime, "Only 1 transaction per block allowed"); // Ensures only 1 transaction per block

        lastBlockTime = block.timestamp;

        // Player wins if the last digit of the block timestamp is less than 5
        if (block.timestamp % 10 < 5) {
            (bool sent,) = msg.sender.call{value: address(this).balance}("");
            require(sent, "Failed to send Ether");
        }
    }
}
```

## 攻击方式与影响
1. 操纵时间机制： 攻击者可以通过修改区块时间戳来利用合约内的基于时间的机制。例如在彩票游戏中，攻击者调整时间戳以匹配特定条件，从而增加获胜机会，或者快速连续地执行函数以耗尽合约资源。
2. 破坏合约稳定性： 使用区块时间戳由于其可操作性可能导致不可预测的结果，导致奖励过早发放或必要的更新被推迟，从而破坏合约操作的稳定性。
3. 协助抢跑攻击： 时间戳操纵可以促进抢跑攻击（front-running），使攻击者能够在战略上有利的时间先于其他人执行交易，这在金融环境中具有极大的破坏性并给他人造成重大损失。

## 检测要点
1. 检查智能合约代码中是否直接使用 block.timestamp 或 now 参与核心业务逻辑的条件判断（如抽奖、发奖、拍卖结束判断）。
2. 检查是否将 block.timestamp 用于伪随机数生成（PRNG）算法中。
3. 评估对时间精度的容忍度，如果业务逻辑依赖于 15 秒以内的精确时间度量，则属于高风险。

## 安全实践
1. 使用外部可信时间源： 为了减轻时间戳操纵的风险并提高智能合约的准确性和安全性，建议使用受信任的外部时间源或多个时间源，这可以帮助确保更可靠的计时。
2. 实施时间宽限期（Time Buffer）： 如果你需要使用 block.timestamp，请考虑添加一个时间缓冲区。这使得矿工更难操纵结束时间，为参与者提供更公平的结果。

修复示例
```solidity
# 安全 - 避免直接依赖时间戳产生随机数，以及在拍卖逻辑中引入宽限期
contract SafeAuction {
    uint256 public auctionEndTime;

    // ... 构造函数与其他逻辑 ...

    function endAuction() external {
        // 如果你需要使用 block.timestamp，考虑添加一个时间缓冲区
        // 例如设置规则：拍卖仅在 block.timestamp 大于拍卖结束时间加上额外一分钟的宽限期后才结束
        require(block.timestamp > auctionEndTime + 1 minutes, "Auction not ended or in grace period");
        
        // ... 结束拍卖并转移资金 ...
    }
}
```
"""
)