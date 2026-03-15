"""
智能合约代数漏洞知识
"""

from ..base import KnowledgeDocument, KnowledgeCategory


INTEGER_OVERFLOW_UNDERFLOW = KnowledgeDocument(
    id="vuln_integer_overflow_underflow",
    title="Integer Overflow and Underflow",
    category=KnowledgeCategory.VULNERABILITY,
    tags=["Integer", "overflow", "underflow"],
    severity="critical",
    cwe_ids=["CWE-190", "CWE-191"],
    owasp_ids=["SC08:2025"],
    content="""
整数上溢出和下溢发生在算术运算产生的值超出了操作数类型可表示的范围时。在 Solidity 0.8+ 中，算术运算默认包含检查，并在发生溢出或下溢时回滚。然而，显式使用 `unchecked` 代码块、汇编或自定义库可能会禁用这些检查。在非 EVM 平台（例如 Move、Sui、Solana、基于 Rust 的链）上，默认的溢出语义有所不同——有些会静默回绕，有些会中止执行——不正确的假设或有缺陷的自定义检查可能导致值回绕、余额计算错误以及不变量被破坏。
这会影响所有执行算术运算的合约类型：DeFi（池不变量、余额、利息、份额）、NFT（供应量、代币 ID）、跨链桥（金额、序列号），以及任何涉及庞大或用户控制数字输入的逻辑。当溢出/下溢破坏经济不变量或促成余额操纵时，影响尤为严重。

## 危险模式

### Solidity 0.8 之前的静默溢出 (EVM)
在 0.8.0 之前的 Solidity 版本中，算术溢出和下溢会静默发生——没有回滚，也没有错误。值会发生回绕（例如，`uint8` 255 + 1 = 0）。
```solidity
# 危险 - 如果 amount 大于余额，将发生下溢并回绕成极大数值

contract VulnerableToken {
    mapping(address => uint256) public balances;

    function transfer(address to, uint256 amount) external {
        balances[msg.sender] -= amount;  // Silent underflow!
        balances[to] += amount;          // Silent overflow possible
    }
}
```

### 非 EVM 链的特定截断语义 (例如 Move 语言)
在 Move 中，加法和乘法在溢出时会中止执行，但左移 (<<) 不会中止——它会静默截断。2025 年 5 月的 Cetus Protocol 漏洞正是因为使用了不正确的阈值，导致拦截失败并在随后的左移中截断溢出。
```Move
# 危险 - 阈值不正确导致防溢出检查失效 (integer-mate 库漏洞)
public fun checked_shlw(n: u256): (u256, bool) {
    let mask = 0xFFFFFFFFFFFFFFFF << 192;  // WRONG! Produces wrong threshold
    if (n > mask) {
        (0, true)   
    } else {
        ((n << 64), false)  // Overflow occurs here for n >= 2^192—Move truncates silently
    }
}
```

### 滥用 unchecked 代码块 (Solidity 0.8+)
即使在 Solidity 0.8+ 上，unchecked 也会禁用检查。
```solidity
# 危险 - 没有对不可控输入进行检查就使用 unchecked
function bad(uint256 x, uint256 y) external pure returns (uint256) {
    unchecked {
        return x * y;  // Can overflow; no revert
    }
}
```

### 攻击方式
1. 利用 Solidity 中假定不可能发生溢出/下溢但确实存在边界情况的 unchecked 代码块。
2. 利用非 EVM 语义，使得静默回绕或自定义检查可以被绕过。
3. 使用巨大或精心构造的输入，在乘法或加法链中触发溢出。
4. 利用破坏不变量的值（例如，溢出产生一个微小的 k，从而通过粗略的检查）。


## 检测要点
检测要点
1. 检查 EVM/Solidity 环境中的特定用法（unchecked 的使用、汇编、0.8 之前的代码库）。
2. 检查非 EVM 链（Move、Sui、Aptos、Solana 等）及其默认的溢出语义。
3. 检查乘法和指数运算（使用大操作数时溢出风险高）。
4. 检查减法和递减操作（当减数 > 被减数时发生下溢）。
5. 检查类型转换和强制转换（例如将 uint256 向下转换为 uint128）。

## 安全实践
1. 在 Solidity/EVM 环境下:除非有充分的理由和证明安全的测试，否则避免使用 unchecked 算术;对关键的不变量使用显式的检查和自定义错误;倾向于使用经过充分审查的数学库（用于定点数、指数等）。
2. 在非 EVM 环境下:了解语言的默认溢出语义;在有条件的地方使用安全的算术结构或库;围绕关键算术逻辑添加断言和不变量。
3.使用极端的数值范围进行测试（所有数值类型的最小和最大值）,针对极有可能发生溢出/下溢的边界情况进行模糊测试（Fuzz tests）。

## 修复示例

```Solidity
# 安全 - 升级到 Solidity 0.8+ 并依赖默认检查
pragma solidity ^0.8.0;

contract SafeToken {
    mapping(address => uint256) public balances;

    function transfer(address to, uint256 amount) external {
        balances[msg.sender] -= amount;  // Reverts on underflow (checked by default)
        balances[to] += amount;          // Reverts on overflow
    }
}
```

```Move
# 安全 - 正确的溢出阈值检查
public fun checked_shlw(n: u256): (u256, bool) {
    // 正确: 如果 n >= 2^192，则左移 64 位会溢出
    if (n >= 1 << 192) {
        (0, true)   // Overflow—abort path
    } else {
        ((n << 64), false)
    }
}
```

"""
)


INSECURE_RANDOMNESS = KnowledgeDocument(
    id="vuln_insecure_randomness",
    title="Insecure Randomness",
    category=KnowledgeCategory.VULNERABILITY,
    tags=["randomness", "predictable"],
    severity="high",
    cwe_ids=["CWE-330", "CWE-338"],
    owasp_ids=["SC09:2025"],
    content="""
随机数生成器对于赌博、游戏获胜者选择和随机种子生成等应用程序至关重要。在以太坊上，由于其确定性，生成随机数具有挑战性。因为 Solidity 无法产生真正的随机数，它依赖于伪随机因素。此外，Solidity 中的复杂计算在 Gas 方面成本高昂。

开发者经常使用与区块相关的方法来生成随机数，例如 `block.timestamp`、`blockhash(uint blockNumber)`、`block.difficulty`、`block.number` 以及 `block.coinbase`。这些方法是不安全的，因为矿工可以操纵它们，从而影响合约的逻辑。


## 危险模式

### 依赖区块属性生成随机数
```solidity
# 危险 - 使用不安全的区块机制生成随机数
function guess(uint256 _guess) public {
    uint256 answer = uint256(
        keccak256(
            abi.encodePacked(block.timestamp, block.difficulty, msg.sender) // Using insecure mechanisms for random number generation
        ) 
    );

    if (_guess == answer) {
        (bool sent,) = msg.sender.call{value: 1 ether}(""); //
        require(sent, "Failed to send Ether"); //
    }
}
```

## 攻击方式
1. 攻击者可以利用不安全的随机性，在游戏、彩票和任何其他依赖随机数生成的合约中获得不公平的优势。
2. 通过预测或操纵本应随机的结果，攻击者可以使结果朝着有利于他们的方向发展。
3. 这可能导致不公平的胜利、其他参与者的财务损失，以及对智能合约完整性和公平性的普遍不信任。
4. 现实中遭受此类攻击的智能合约案例包括 Roast Football Hack 和 FFIST Hack。

## 检测要点
1. 查找是否使用了 block.timestamp（当前区块时间戳）作为随机源。
2.查找是否使用了 blockhash(uint blockNumber)（给定区块的哈希，仅限最近的 256 个区块）。
3. 查找是否使用了 block.difficulty（当前区块难度）。
4. 查找是否使用了 block.number（当前区块号）或 block.coinbase（当前区块矿工地址）。

## 安全实践
1. 使用预言机（如 Oraclize）作为外部随机性来源；在信任预言机时应谨慎，可以同时使用多个预言机。
2. 使用承诺方案（Commitment Schemes），这是一种采用提交-揭示（commit-reveal）方法的密码学原语，例如 RANDAO。它在抛硬币、零知识证明和安全计算中有广泛应用。
3. 使用 Chainlink VRF，这是一种可证明公平且可验证的随机数生成器 (RNG)，使智能合约能够在不影响安全性或可用性的情况下访问随机值。
4. 考虑 Signidice 算法，适用于使用密码学签名的两方应用程序中的伪随机数生成器 (PRNG)。
5. 使用比特币区块哈希（例如通过 BTCRelay 等预言机作为桥梁），以太坊上的合约可以请求来自比特币区块链的未来区块哈希作为熵源；但需注意这种方法无法防范矿工激励问题，应谨慎实施。
 
## 修复示例
```solidity 
# 安全 - 使用 Chainlink VRFConsumerBase 获取安全的随机数
import "@chainlink/contracts/src/v0.8/VRFConsumerBase.sol"; //

contract Solidity_InsecureRandomness is VRFConsumerBase { //
    // ... 构造函数初始化 VRF ...

    function requestRandomNumber() public returns (bytes32 requestId) {
        require(LINK.balanceOf(address(this)) >= fee, "Not enough LINK"); //
        return requestRandomness(keyHash, fee); //
    }

    function fulfillRandomness(bytes32 requestId, uint256 randomness) internal override {
        randomResult = randomness; //
    }

    function guess(uint256 _guess) public {
        require(randomResult > 0, "Random number not generated yet"); //
        if (_guess == randomResult) { //
            (bool sent,) = msg.sender.call{value: 1 ether}(""); //
            require(sent, "Failed to send Ether"); //
        }
    }
}
```
 
""",
)

ARITHMETIC_ERRORS = KnowledgeDocument(
    id="vuln_arithmetic_errors",
    title="Arithmetic Errors",
    category=KnowledgeCategory.VULNERABILITY,
    tags=["math", "precision", "rounding"],
    severity="high",
    cwe_ids=["CWE-682"],
    owasp_ids=["SC07:2026"],
    content="""
算术错误（舍入和精度丢失）描述了智能合约由于截断、缩放或单位转换执行基于整数的计算而产生不正确或可被利用的结果的任何情况。智能合约仅限于整数算术；任何除法、定点缩放或单位之间的转换都可能丢失精度、引入不对称的舍入，或者导致溢出/下溢。
这会影响所有计算数值的合约类型：DeFi（份额铸造/销毁、LP 代币、利息累积、兑换输出、AMM 不变量更新）、收益金库和 ERC-4626、变基代币、奖励分配以及 NFT/代币经济学。在非 EVM 链上，整数语义和可用精度有所不同，但同样的风险适用于任何由算术驱动经济结果的地方。

## 危险模式

### 脆弱的份额计算逻辑
```solidity
# 危险 - 向下取整截断，在对抗性序列下可能偏袒存款人
contract VulnerableShares {
    // ... 状态变量 ...
    function deposit(uint256 assets) external {
        require(assets > 0, "zero"); //

        uint256 shares;
        if (totalShares == 0) {
            shares = assets; //
        } else {
            // Rounds down and may favor the depositor under certain edge states
            shares = (assets * totalShares) / totalAssets; //
        }

        totalAssets += assets; //
        totalShares += shares; //
        balanceOf[msg.sender] += shares; //
    }
}
# 上述代码中的舍入始终会被截断；在存款/取款的对抗序列下，这可能会被操纵。此外，它没有不变量测试来确保总份额价值在边缘情况下保持一致。
```

## 攻击方式
1. 利用舍入偏差（例如，在对抗序列下偏袒存款人或协议的舍入）。
2. 通过闪电贷或高频交互获取重复的小额收益。
3. 利用公式失效的边缘情况（例如总供应量为零、第一个存款人、极端比率）。
4. 利用在多个操作中累积的多步计算中的精度损失。
5. 结合闪电贷或业务逻辑缺陷，算术错误会被放大为榨取协议资产的漏洞。例如，2025 年 2 月 zkLend 因向下取整导致 950 万美元损失；同年 9 月 Bunni 因提款函数舍入逻辑的精度错误损失 840 万美元。

## 检测要点
1. 审查份额和 LP 代币计算（存款/取款公式、舍入方向）。
2. 审查利息和奖励的累积（复利、时间加权平均值）。
3. 审查 Swap 和 AMM 数学（恒定乘积、集中流动性、输出计算）。
4. 审查定点数和缩放（1e18、1e8 约定、跨代币转换）。
5. 审查变基和按比例分配（每个用户与全局记账）。

## 安全实践
1. 使用安全的数学模式。
2. 清楚地记录并测试您的舍入策略：决定舍入应偏袒协议还是用户，并证明重复交互不会产生“免费价值”。
3. 对于复杂操作（如定点数学、高精度求幂或对数），依赖经过充分审查的数学库。
4. 结合不变量检查（例如，totalAssets 与用户余额总和的对比，或操作后份额/价值的一致性）。
5. 使用模糊测试和差异测试（Fuzz testing and differential testing）来发现围绕大/小值和重复操作的边缘情况。

##修复示例
```solidity
# 安全 - 健壮的算术和感知不变量的设计
contract SaferShares {
    // ... 状态变量和自定义错误 ...
    function deposit(uint256 assets) external {
        if (assets == 0) revert ZeroAmount(); //

        uint256 shares;
        if (totalShares == 0 || totalAssets == 0) {
            // Explicitly define initial conditions
            shares = assets; //
        } else {
            // Use rounding strategy intentionally (up or down) and test it
            shares = (assets * totalShares + totalAssets - 1) / totalAssets; // round up
        }

        uint256 newTotalAssets = totalAssets + assets; //
        if (newTotalAssets < totalAssets) revert InvalidState(); // overflow guard

        totalAssets = newTotalAssets; //
        totalShares += shares; //
        balanceOf[msg.sender] += shares; //
    }
}
```

"""
)
