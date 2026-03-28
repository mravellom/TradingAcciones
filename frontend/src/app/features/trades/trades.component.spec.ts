import { ComponentFixture, TestBed } from '@angular/core/testing';
import { provideHttpClient } from '@angular/common/http';
import { provideHttpClientTesting } from '@angular/common/http/testing';
import { TradesComponent } from './trades.component';

describe('TradesComponent', () => {
  let component: TradesComponent;
  let fixture: ComponentFixture<TradesComponent>;

  beforeEach(async () => {
    await TestBed.configureTestingModule({
      imports: [TradesComponent],
      providers: [provideHttpClient(), provideHttpClientTesting()],
    }).compileComponents();

    fixture = TestBed.createComponent(TradesComponent);
    component = fixture.componentInstance;
  });

  it('should create', () => {
    expect(component).toBeTruthy();
  });

  it('should start with trades tab active', () => {
    expect(component.activeTab).toBe('trades');
  });

  it('should start with empty trades', () => {
    expect(component.trades).toEqual([]);
  });

  it('should return correct PnL class', () => {
    expect(component.getPnlClass('100')).toBe('positive');
    expect(component.getPnlClass('-50')).toBe('negative');
    expect(component.getPnlClass('0')).toBe('neutral');
  });

  it('should return correct status class', () => {
    expect(component.getStatusClass('FILLED')).toBe('badge-buy');
    expect(component.getStatusClass('REJECTED')).toBe('badge-sell');
    expect(component.getStatusClass('SUBMITTED')).toBe('badge-open');
  });
});
