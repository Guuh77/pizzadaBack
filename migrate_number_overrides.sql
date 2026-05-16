-- Migration: Add number_overrides column to pizza_configs
-- Stores admin-defined pizza number swaps as JSON { pizzaId: assignedNumber }
ALTER TABLE pizza_configs ADD (number_overrides CLOB DEFAULT '{}');
