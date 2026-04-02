import { Component, OnInit } from '@angular/core';
import { CommonModule } from '@angular/common';
import { FormsModule } from '@angular/forms';
import { ApiService } from '../../core/services/api.service';

interface Strategy {
  id: string;
  name: string;
  description: string;
  strategy_type: string;
  parameters: Record<string, any>;
  symbols: string[];
  timeframe: string;
  is_active: boolean;
  version: number;
  created_at: string;
  asset_class?: string;
}

@Component({
  selector: 'app-strategies',
  standalone: true,
  imports: [CommonModule, FormsModule],
  templateUrl: './strategies.component.html',
  styleUrl: './strategies.component.scss',
})
export class StrategiesComponent implements OnInit {
  strategies: Strategy[] = [];
  perStrategyPerf: any[] = [];
  showCreateForm = false;

  newStrategy = {
    name: '',
    description: '',
    strategy_type: 'momentum',
    asset_class: 'CRYPTO',
    parameters: '{}',
    symbols: 'BTCUSDT,ETHUSDT',
    timeframe: '1h',
  };

  constructor(private api: ApiService) {}

  ngOnInit(): void {
    this.loadData();
  }

  loadData(): void {
    this.api.getStrategies().subscribe((s) => (this.strategies = s));
    this.api.getPerStrategyPerformance().subscribe((p) => (this.perStrategyPerf = p));
  }

  toggleActive(strategy: Strategy): void {
    if (strategy.is_active) {
      this.api.deactivateStrategy(strategy.id).subscribe(() => this.loadData());
    } else {
      this.api.activateStrategy(strategy.id).subscribe(() => this.loadData());
    }
  }

  createStrategy(): void {
    const data = {
      name: this.newStrategy.name,
      description: this.newStrategy.description,
      strategy_type: this.newStrategy.strategy_type,
      parameters: JSON.parse(this.newStrategy.parameters),
      symbols: this.newStrategy.symbols.split(',').map((s) => s.trim()),
      timeframe: this.newStrategy.timeframe,
    };
    this.api.createStrategy(data).subscribe(() => {
      this.showCreateForm = false;
      this.resetForm();
      this.loadData();
    });
  }

  onAssetClassChange(): void {
    if (this.newStrategy.asset_class === 'STOCKS') {
      this.newStrategy.symbols = 'AAPL,MSFT,GOOGL,NVDA';
      this.newStrategy.timeframe = '1d';
      this.newStrategy.strategy_type = 'stock_momentum';
    } else {
      this.newStrategy.symbols = 'BTCUSDT,ETHUSDT';
      this.newStrategy.timeframe = '1h';
      this.newStrategy.strategy_type = 'momentum';
    }
  }

  resetForm(): void {
    this.newStrategy = {
      name: '',
      description: '',
      strategy_type: 'momentum',
      asset_class: 'CRYPTO',
      parameters: '{}',
      symbols: 'BTCUSDT,ETHUSDT',
      timeframe: '1h',
    };
  }

  getPerf(strategyId: string): any | null {
    return this.perStrategyPerf.find((p) => p.strategy_id === strategyId) || null;
  }

  formatPercent(value: number): string {
    return (value * 100).toFixed(1) + '%';
  }

  formatParams(params: Record<string, any>): string {
    return Object.entries(params)
      .map(([k, v]) => `${k}: ${v}`)
      .join(', ');
  }
}
