-- Inventory Share Plugin database schema
-- Run this SQL on your MySQL server before using the plugin.

CREATE DATABASE IF NOT EXISTS player_data;

USE player_data;

CREATE TABLE IF NOT EXISTS player_data (
    player_xuid VARCHAR(64) PRIMARY KEY,
    player_inv MEDIUMTEXT DEFAULT NULL,
    player_enderchest MEDIUMTEXT DEFAULT NULL,
    is_logged_in TINYINT NOT NULL DEFAULT 0,
    session_token VARCHAR(36) DEFAULT NULL,
    unresolved_items MEDIUMTEXT DEFAULT NULL,
    player_xp_level INT DEFAULT 0,
    player_xp_progress FLOAT DEFAULT 0.0,
    player_money_score INT DEFAULT 0,
    player_tags MEDIUMTEXT DEFAULT NULL,
    player_locations MEDIUMTEXT DEFAULT NULL,
    player_bundles MEDIUMTEXT DEFAULT NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
