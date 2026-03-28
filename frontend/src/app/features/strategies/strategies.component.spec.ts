import { ComponentFixture, TestBed } from '@angular/core/testing';
import { provideHttpClient } from '@angular/common/http';
import { provideHttpClientTesting } from '@angular/common/http/testing';
import { StrategiesComponent } from './strategies.component';

describe('StrategiesComponent', () => {
  let component: StrategiesComponent;
  let fixture: ComponentFixture<StrategiesComponent>;

  beforeEach(async () => {
    await TestBed.configureTestingModule({
      imports: [StrategiesComponent],
      providers: [provideHttpClient(), provideHttpClientTesting()],
    }).compileComponents();

    fixture = TestBed.createComponent(StrategiesComponent);
    component = fixture.componentInstance;
  });

  it('should create', () => {
    expect(component).toBeTruthy();
  });

  it('should start with create form hidden', () => {
    expect(component.showCreateForm).toBe(false);
  });

  it('should have default strategy values', () => {
    expect(component.newStrategy.strategy_type).toBe('momentum');
    expect(component.newStrategy.timeframe).toBe('1h');
  });

  it('should reset form', () => {
    component.newStrategy.name = 'Test';
    component.resetForm();
    expect(component.newStrategy.name).toBe('');
  });

  it('should format percent', () => {
    expect(component.formatPercent(0.75)).toBe('75.0%');
  });

  it('should format params', () => {
    expect(component.formatParams({ rsi: 14, sma: 20 })).toBe('rsi: 14, sma: 20');
  });

  it('should return null for unknown strategy perf', () => {
    expect(component.getPerf('unknown-id')).toBeNull();
  });
});
