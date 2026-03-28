import { ComponentFixture, TestBed } from '@angular/core/testing';
import { provideHttpClient } from '@angular/common/http';
import { provideHttpClientTesting } from '@angular/common/http/testing';
import { RiskPanelComponent } from './risk-panel.component';

describe('RiskPanelComponent', () => {
  let component: RiskPanelComponent;
  let fixture: ComponentFixture<RiskPanelComponent>;

  beforeEach(async () => {
    await TestBed.configureTestingModule({
      imports: [RiskPanelComponent],
      providers: [provideHttpClient(), provideHttpClientTesting()],
    }).compileComponents();

    fixture = TestBed.createComponent(RiskPanelComponent);
    component = fixture.componentInstance;
  });

  it('should create', () => {
    expect(component).toBeTruthy();
  });

  it('should start with null risk status', () => {
    expect(component.riskStatus).toBeNull();
  });

  it('should format percent correctly', () => {
    expect(component.formatPercent('0.03')).toBe('3.00%');
  });

  it('should return correct check class', () => {
    expect(component.getCheckClass('healthy')).toBe('positive');
    expect(component.getCheckClass('unhealthy')).toBe('negative');
    expect(component.getCheckClass('unknown')).toBe('neutral');
  });
});
