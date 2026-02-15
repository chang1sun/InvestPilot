-- ============================================================
-- InvestPilot Database Initialization Script
-- ============================================================
-- Description: Complete database schema for InvestPilot
-- Database: MySQL 8.0+ / MariaDB 10.5+ (also SQLite compatible)
-- Created: 2026-01-04
-- Updated: 2026-02-15  Added is_admin, tracking tables
-- ============================================================

-- Set character set and collation
SET NAMES utf8mb4;
SET CHARACTER SET utf8mb4;

-- ============================================================
-- 1. Users Table
-- ============================================================
CREATE TABLE IF NOT EXISTS `users` (
  `id` INT AUTO_INCREMENT PRIMARY KEY,
  `nickname` VARCHAR(100) NOT NULL COMMENT 'User nickname',
  `email` VARCHAR(200) NOT NULL UNIQUE COMMENT 'User email',
  `password_hash` VARCHAR(128) NOT NULL COMMENT 'Password hash (bcrypt)',
  `session_id` VARCHAR(64) UNIQUE COMMENT 'Session ID for auto-login',
  `is_admin` BOOLEAN NOT NULL DEFAULT 0 COMMENT 'Admin flag for privileged API access',
  `email_subscribed` BOOLEAN NOT NULL DEFAULT 1 COMMENT 'Whether user receives email notifications',
  `created_at` DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP COMMENT 'Creation timestamp',
  `last_login` DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP COMMENT 'Last login timestamp',
  INDEX `idx_email` (`email`),
  INDEX `idx_session_id` (`session_id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='User accounts';

-- ============================================================
-- 2. Accounts Table
-- ============================================================
CREATE TABLE IF NOT EXISTS `accounts` (
  `id` INT AUTO_INCREMENT PRIMARY KEY,
  `user_id` INT NOT NULL UNIQUE COMMENT 'User ID (FK)',
  `currency` VARCHAR(10) NOT NULL DEFAULT 'USD' COMMENT 'Account currency',
  `total_deposit` FLOAT NOT NULL DEFAULT 0 COMMENT 'Total deposits',
  `total_withdrawal` FLOAT NOT NULL DEFAULT 0 COMMENT 'Total withdrawals',
  `realized_profit_loss` FLOAT NOT NULL DEFAULT 0 COMMENT 'Realized P&L',
  `created_at` DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  `updated_at` DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  INDEX `idx_user_id` (`user_id`),
  CONSTRAINT `fk_account_user` FOREIGN KEY (`user_id`) REFERENCES `users`(`id`) ON DELETE CASCADE,
  CONSTRAINT `unique_user_currency` UNIQUE (`user_id`, `currency`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='User accounts';

-- ============================================================
-- 3. Cash Flows Table
-- ============================================================
CREATE TABLE IF NOT EXISTS `cash_flows` (
  `id` INT AUTO_INCREMENT PRIMARY KEY,
  `account_id` INT NOT NULL COMMENT 'Account ID (FK)',
  `user_id` INT NOT NULL COMMENT 'User ID (FK)',
  `flow_type` VARCHAR(20) NOT NULL COMMENT 'DEPOSIT or WITHDRAWAL',
  `flow_date` DATE NOT NULL COMMENT 'Flow date',
  `amount` FLOAT NOT NULL COMMENT 'Amount (positive)',
  `currency` VARCHAR(10) NOT NULL DEFAULT 'USD' COMMENT 'Currency',
  `notes` TEXT COMMENT 'Notes',
  `source` VARCHAR(20) DEFAULT 'manual' COMMENT 'Source: manual, auto',
  `created_at` DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  `updated_at` DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  INDEX `idx_account_id` (`account_id`),
  INDEX `idx_user_id` (`user_id`),
  INDEX `idx_flow_type` (`flow_type`),
  INDEX `idx_flow_date` (`flow_date`),
  CONSTRAINT `fk_cashflow_account` FOREIGN KEY (`account_id`) REFERENCES `accounts`(`id`) ON DELETE CASCADE,
  CONSTRAINT `fk_cashflow_user` FOREIGN KEY (`user_id`) REFERENCES `users`(`id`) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='Cash flow records';

-- ============================================================
-- 4. Portfolios Table
-- ============================================================
CREATE TABLE IF NOT EXISTS `portfolios` (
  `id` INT AUTO_INCREMENT PRIMARY KEY,
  `user_id` INT NOT NULL COMMENT 'User ID (FK)',
  `symbol` VARCHAR(32) NOT NULL COMMENT 'Asset symbol',
  `asset_type` VARCHAR(20) NOT NULL DEFAULT 'STOCK' COMMENT 'STOCK, CRYPTO, GOLD, CASH',
  `currency` VARCHAR(10) NOT NULL DEFAULT 'USD' COMMENT 'Currency',
  `total_quantity` FLOAT NOT NULL DEFAULT 0 COMMENT 'Total quantity',
  `avg_cost` FLOAT NOT NULL DEFAULT 0 COMMENT 'Average cost',
  `total_cost` FLOAT NOT NULL DEFAULT 0 COMMENT 'Total cost',
  `created_at` DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  `updated_at` DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  INDEX `idx_user_id` (`user_id`),
  INDEX `idx_symbol` (`symbol`),
  CONSTRAINT `fk_portfolio_user` FOREIGN KEY (`user_id`) REFERENCES `users`(`id`) ON DELETE CASCADE,
  CONSTRAINT `unique_user_symbol_asset_currency` UNIQUE (`user_id`, `symbol`, `asset_type`, `currency`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='User portfolios';

-- ============================================================
-- 5. Transactions Table
-- ============================================================
CREATE TABLE IF NOT EXISTS `transactions` (
  `id` INT AUTO_INCREMENT PRIMARY KEY,
  `portfolio_id` INT NOT NULL COMMENT 'Portfolio ID (FK)',
  `user_id` INT NOT NULL COMMENT 'User ID (FK)',
  `transaction_type` VARCHAR(10) NOT NULL COMMENT 'BUY or SELL',
  `trade_date` DATE NOT NULL COMMENT 'Trade date',
  `price` FLOAT NOT NULL COMMENT 'Trade price',
  `quantity` FLOAT NOT NULL COMMENT 'Trade quantity',
  `amount` FLOAT NOT NULL COMMENT 'Trade amount (price * quantity)',
  `cost_basis` FLOAT DEFAULT 0 COMMENT 'Cost basis (for SELL)',
  `realized_profit_loss` FLOAT DEFAULT 0 COMMENT 'Realized P&L (for SELL)',
  `notes` TEXT COMMENT 'Notes',
  `source` VARCHAR(20) DEFAULT 'manual' COMMENT 'Source: manual, ai_suggestion',
  `created_at` DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  `updated_at` DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  INDEX `idx_portfolio_id` (`portfolio_id`),
  INDEX `idx_user_id` (`user_id`),
  INDEX `idx_trade_date` (`trade_date`),
  CONSTRAINT `fk_transaction_portfolio` FOREIGN KEY (`portfolio_id`) REFERENCES `portfolios`(`id`) ON DELETE CASCADE,
  CONSTRAINT `fk_transaction_user` FOREIGN KEY (`user_id`) REFERENCES `users`(`id`) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='Transaction records';

-- ============================================================
-- 6. Tasks Table
-- ============================================================
CREATE TABLE IF NOT EXISTS `tasks` (
  `id` INT AUTO_INCREMENT PRIMARY KEY,
  `task_id` VARCHAR(64) NOT NULL UNIQUE COMMENT 'Task UUID',
  `user_id` INT NOT NULL COMMENT 'User ID (FK)',
  `task_type` VARCHAR(50) NOT NULL COMMENT 'Task type',
  `status` VARCHAR(20) NOT NULL DEFAULT 'running' COMMENT 'running, completed, terminated, failed',
  `task_params` TEXT COMMENT 'Task parameters (JSON)',
  `task_result` TEXT COMMENT 'Task result (JSON)',
  `error_message` TEXT COMMENT 'Error message',
  `created_at` DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  `started_at` DATETIME COMMENT 'Start timestamp',
  `completed_at` DATETIME COMMENT 'Completion timestamp',
  INDEX `idx_task_id` (`task_id`),
  INDEX `idx_user_id` (`user_id`),
  INDEX `idx_status` (`status`),
  INDEX `idx_created_at` (`created_at`),
  CONSTRAINT `fk_task_user` FOREIGN KEY (`user_id`) REFERENCES `users`(`id`) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='Async tasks';

-- ============================================================
-- 7. Analysis Logs Table
-- ============================================================
CREATE TABLE IF NOT EXISTS `analysis_logs` (
  `id` INT AUTO_INCREMENT PRIMARY KEY,
  `symbol` VARCHAR(32) NOT NULL COMMENT 'Asset symbol',
  `market_date` DATE NOT NULL COMMENT 'Market data date',
  `model_name` VARCHAR(50) NOT NULL COMMENT 'Model name',
  `language` VARCHAR(10) NOT NULL COMMENT 'Analysis language',
  `analysis_result` TEXT COMMENT 'Analysis result (JSON)',
  `created_at` DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  INDEX `idx_symbol` (`symbol`),
  INDEX `idx_market_date` (`market_date`),
  CONSTRAINT `unique_analysis` UNIQUE (`symbol`, `market_date`, `model_name`, `language`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='Analysis logs';

-- ============================================================
-- 8. Stock Trade Signals Table
-- ============================================================
CREATE TABLE IF NOT EXISTS `stock_trade_signals` (
  `id` INT AUTO_INCREMENT PRIMARY KEY,
  `symbol` VARCHAR(32) NOT NULL COMMENT 'Asset symbol',
  `date` DATE NOT NULL COMMENT 'Signal date',
  `price` FLOAT NOT NULL COMMENT 'Signal price',
  `signal_type` VARCHAR(10) NOT NULL COMMENT 'BUY, SELL, HOLD',
  `reason` TEXT COMMENT 'Signal reason',
  `source` VARCHAR(20) DEFAULT 'ai' COMMENT 'Source: ai, local',
  `model_name` VARCHAR(50) NOT NULL COMMENT 'Model name',
  `asset_type` VARCHAR(20) DEFAULT 'STOCK' COMMENT 'STOCK, CRYPTO, COMMODITY, BOND',
  `adopted` BOOLEAN DEFAULT FALSE COMMENT 'Whether adopted by user',
  `related_transaction_id` INT COMMENT 'Related transaction ID (FK)',
  `user_id` INT COMMENT 'User ID who adopted (FK)',
  `created_at` DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  INDEX `idx_symbol` (`symbol`),
  INDEX `idx_date` (`date`),
  INDEX `idx_model_name` (`model_name`),
  INDEX `idx_asset_type` (`asset_type`),
  INDEX `idx_adopted` (`adopted`),
  INDEX `idx_related_transaction` (`related_transaction_id`),
  INDEX `idx_user_id` (`user_id`),
  CONSTRAINT `fk_signal_transaction` FOREIGN KEY (`related_transaction_id`) REFERENCES `transactions`(`id`) ON DELETE SET NULL,
  CONSTRAINT `fk_signal_user` FOREIGN KEY (`user_id`) REFERENCES `users`(`id`) ON DELETE SET NULL,
  CONSTRAINT `unique_symbol_date_model_asset` UNIQUE (`symbol`, `date`, `model_name`, `asset_type`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='Stock trade signals';

-- ============================================================
-- 9. Recommendation Cache Table
-- ============================================================
CREATE TABLE IF NOT EXISTS `recommendation_cache` (
  `id` INT AUTO_INCREMENT PRIMARY KEY,
  `cache_date` DATE NOT NULL COMMENT 'Cache date',
  `model_name` VARCHAR(50) NOT NULL COMMENT 'Model name',
  `language` VARCHAR(10) NOT NULL COMMENT 'Language',
  `criteria_hash` VARCHAR(64) NOT NULL COMMENT 'Criteria hash',
  `recommendation_result` TEXT COMMENT 'Recommendation result (JSON)',
  `created_at` DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  INDEX `idx_cache_date` (`cache_date`),
  CONSTRAINT `unique_recommendation_cache` UNIQUE (`cache_date`, `model_name`, `language`, `criteria_hash`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='Recommendation cache';

-- ============================================================
-- 10. Tracking Stocks Table (AI Curated Portfolio)
-- ============================================================
CREATE TABLE IF NOT EXISTS `tracking_stocks` (
  `id` INT AUTO_INCREMENT PRIMARY KEY,
  `symbol` VARCHAR(32) NOT NULL UNIQUE COMMENT 'Stock ticker symbol',
  `name` VARCHAR(128) COMMENT 'Stock display name',
  `buy_price` FLOAT NOT NULL COMMENT 'Price when added to the list',
  `buy_date` DATE NOT NULL COMMENT 'Date added to the list',
  `current_price` FLOAT COMMENT 'Latest cached price',
  `cost_amount` FLOAT COMMENT 'Actual capital invested',
  `sector` VARCHAR(64) COMMENT 'GICS sector (e.g. Technology)',
  `industry` VARCHAR(128) COMMENT 'Sub-industry (e.g. Semiconductors)',
  `reason` TEXT COMMENT 'AI reasoning for buying',
  `created_at` DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  `updated_at` DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  INDEX `idx_ts_symbol` (`symbol`),
  INDEX `idx_ts_buy_date` (`buy_date`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='AI curated tracking portfolio holdings';

-- ============================================================
-- 11. Tracking Transactions Table
-- ============================================================
CREATE TABLE IF NOT EXISTS `tracking_transactions` (
  `id` INT AUTO_INCREMENT PRIMARY KEY,
  `symbol` VARCHAR(32) NOT NULL COMMENT 'Stock ticker symbol',
  `name` VARCHAR(128) COMMENT 'Stock display name',
  `action` VARCHAR(10) NOT NULL COMMENT 'BUY or SELL',
  `price` FLOAT NOT NULL COMMENT 'Transaction price',
  `date` DATE NOT NULL COMMENT 'Transaction date',
  `reason` TEXT COMMENT 'AI reasoning',
  `buy_price` FLOAT COMMENT 'Original buy price (for SELL)',
  `realized_pct` FLOAT COMMENT 'Realized return % (for SELL)',
  `cost_amount` FLOAT COMMENT 'Actual capital invested (for BUY)',
  `created_at` DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  INDEX `idx_tt_symbol` (`symbol`),
  INDEX `idx_tt_action` (`action`),
  INDEX `idx_tt_date` (`date`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='Tracking portfolio buy/sell transactions';

-- ============================================================
-- 12. Tracking Daily Snapshots Table
-- ============================================================
CREATE TABLE IF NOT EXISTS `tracking_daily_snapshots` (
  `id` INT AUTO_INCREMENT PRIMARY KEY,
  `date` DATE NOT NULL UNIQUE COMMENT 'Snapshot date',
  `portfolio_value` FLOAT NOT NULL COMMENT 'Total portfolio value',
  `cash` FLOAT NOT NULL COMMENT 'Remaining cash',
  `holdings_value` FLOAT NOT NULL COMMENT 'Sum of holding values',
  `total_return_pct` FLOAT NOT NULL DEFAULT 0 COMMENT 'Total return % since inception',
  `realized_pnl` FLOAT NOT NULL DEFAULT 0 COMMENT 'Cumulative realized P&L',
  `holdings_json` TEXT COMMENT 'JSON snapshot of holdings at this date',
  `created_at` DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  INDEX `idx_tds_date` (`date`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='Daily portfolio value snapshots for charting';

-- ============================================================
-- 13. Tracking Decision Logs Table
-- ============================================================
CREATE TABLE IF NOT EXISTS `tracking_decision_logs` (
  `id` INT AUTO_INCREMENT PRIMARY KEY,
  `date` DATE NOT NULL COMMENT 'Decision date',
  `model_name` VARCHAR(50) NOT NULL COMMENT 'AI model used',
  `has_changes` BOOLEAN DEFAULT FALSE COMMENT 'Whether portfolio was updated',
  `summary` TEXT COMMENT 'AI market summary / reasoning',
  `actions_json` TEXT COMMENT 'JSON list of actions taken',
  `raw_response` TEXT COMMENT 'Full AI response for debugging',
  `elapsed_seconds` FLOAT COMMENT 'Pipeline execution time',
  `report_json` TEXT COMMENT 'Full structured daily report (JSON)',
  `market_regime` VARCHAR(20) COMMENT 'RISK-ON / NEUTRAL / RISK-OFF',
  `confidence_level` VARCHAR(20) COMMENT 'HIGH / MEDIUM / LOW',
  `accuracy_score` FLOAT COMMENT 'Overall accuracy 0-100 (T+5 evaluation)',
  `accuracy_details` TEXT COMMENT 'JSON: per-action outcome details',
  `accuracy_evaluated_at` DATETIME COMMENT 'When the accuracy evaluation was done',
  `created_at` DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  INDEX `idx_tdl_date` (`date`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='AI decision run logs with accuracy tracking';

-- ============================================================
-- Display Table Information
-- ============================================================
SELECT 'Database initialization completed!' AS Status;

-- Show all tables
SHOW TABLES;

-- Show table statistics
SELECT 
    TABLE_NAME as 'Table',
    TABLE_ROWS as 'Rows',
    ROUND(DATA_LENGTH / 1024 / 1024, 2) as 'Data Size (MB)',
    ROUND(INDEX_LENGTH / 1024 / 1024, 2) as 'Index Size (MB)'
FROM information_schema.TABLES
WHERE TABLE_SCHEMA = DATABASE()
ORDER BY TABLE_NAME;
