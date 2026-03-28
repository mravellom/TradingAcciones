import { ComponentFixture, TestBed } from '@angular/core/testing';
import { provideHttpClient } from '@angular/common/http';
import { provideHttpClientTesting } from '@angular/common/http/testing';
import { AnalyticsComponent } from './analytics.component';

describe('AnalyticsComponent', () => {
  let component: AnalyticsComponent;
  let fixture: ComponentFixture<AnalyticsComponent>;

  beforeEach(async () => {
    await TestBed.configureTestingModule({
      imports: [AnalyticsComponent],
      providers: [provideHttpClient(), provideHttpClientTesting()],
    }).compileComponents();

    fixture = TestBed.createComponent(AnalyticsComponent);
    component = fixture.componentInstance;
  });

  it('should create', () => {
    expect(component).toBeTruthy();
  });

  it('should start with null summary', () => {
    expect(component.summary).toBeNull();
  });

  it('should start with empty data arrays', () => {
    expect(component.pnlData).toEqual([]);
    expect(component.drawdownData).toEqual([]);
    expect(component.strategyPerf).toEqual([]);
  });

  it('should format USD correctly', () => {
    expect(component.formatUsd('1234.5')).toBe('1,234.50');
  });

  it('should return correct PnL class', () => {
    expect(component.getPnlClass('100')).toBe('positive');
    expect(component.getPnlClass('-50')).toBe('negative');
    expect(component.getPnlClass(0)).toBe('neutral');
  });

  it('should calculate PnL bar width', () => {
    component.pnlData = [
      { cumulative_pnl: '100' },
      { cumulative_pnl: '-50' },
    ];
    expect(component.getPnlBarWidth('100')).toBe(100);
    expect(component.getPnlBarWidth('-50')).toBe(50);
  });

  it('should return 0 bar width with no data', () => {
    expect(component.getPnlBarWidth('100')).toBe(0);
  });
});
