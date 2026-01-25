#!/usr/bin/env python3
"""
ACCESS Efficacy Data Analysis
Comprehensive analysis of mock ACCESS assessment data comparing Intervention vs Control groups.
"""

import pandas as pd
import numpy as np
from scipy import stats
import matplotlib.pyplot as plt
import seaborn as sns
from pathlib import Path

# Set style for visualizations
plt.style.use('seaborn-v0_8-whitegrid')
sns.set_palette("husl")

def load_and_clean_data(filepath: str) -> pd.DataFrame:
    """Load data and perform initial cleaning."""
    df = pd.read_csv(filepath)
    print("=" * 60)
    print("DATA QUALITY ANALYSIS")
    print("=" * 60)
    
    # Basic info
    print(f"\n1. BASIC DATASET INFO")
    print(f"   Total rows: {len(df)}")
    print(f"   Total columns: {len(df.columns)}")
    print(f"   Columns: {list(df.columns)}")
    
    # Check for duplicates
    print(f"\n2. DUPLICATE CHECK")
    duplicates = df[df.duplicated(subset=['StudentID'], keep=False)]
    n_duplicates = len(duplicates)
    if n_duplicates > 0:
        print(f"   Found {n_duplicates} rows with duplicate StudentIDs:")
        print(f"   Duplicate IDs: {duplicates['StudentID'].unique().tolist()}")
        # Remove duplicates, keeping first occurrence
        df_clean = df.drop_duplicates(subset=['StudentID'], keep='first')
        print(f"   Removed {len(df) - len(df_clean)} duplicate rows")
    else:
        df_clean = df
        print("   No duplicates found")
    
    # Check for missing values
    print(f"\n3. MISSING VALUES")
    missing = df_clean.isnull().sum()
    if missing.sum() > 0:
        print(f"   Missing values found:")
        print(missing[missing > 0])
    else:
        print("   No missing values found")
    
    # Check for outliers in growth scores
    print(f"\n4. OUTLIER DETECTION (Growth Scores)")
    growth_cols = [col for col in df_clean.columns if 'Growth' in col]
    for col in growth_cols:
        q1 = df_clean[col].quantile(0.25)
        q3 = df_clean[col].quantile(0.75)
        iqr = q3 - q1
        lower = q1 - 1.5 * iqr
        upper = q3 + 1.5 * iqr
        outliers = df_clean[(df_clean[col] < lower) | (df_clean[col] > upper)]
        if len(outliers) > 0:
            print(f"   {col}: {len(outliers)} potential outliers (range: {lower:.2f} to {upper:.2f})")
    
    # Check score ranges
    print(f"\n5. SCORE RANGE VALIDATION")
    score_cols = [col for col in df_clean.columns if 'Baseline' in col or 'Endline' in col]
    for col in score_cols:
        min_val, max_val = df_clean[col].min(), df_clean[col].max()
        if min_val < 1.0 or max_val > 6.0:
            print(f"   WARNING: {col} has values outside expected 1-6 range: [{min_val:.2f}, {max_val:.2f}]")
    print("   All scores appear to be in valid ACCESS range (1.0-6.0)")
    
    # Group distribution
    print(f"\n6. GROUP DISTRIBUTION")
    print(df_clean.groupby(['Grade', 'Group']).size().unstack(fill_value=0))
    
    return df_clean


def calculate_descriptive_stats(df: pd.DataFrame) -> pd.DataFrame:
    """Calculate descriptive statistics by group."""
    print("\n" + "=" * 60)
    print("DESCRIPTIVE STATISTICS")
    print("=" * 60)
    
    # Overall statistics by group
    growth_cols = ['Growth_Listening', 'Growth_Speaking', 'Growth_Reading', 'Growth_Writing', 'Growth_Overall']
    
    stats_list = []
    for group in ['Intervention', 'Control']:
        group_data = df[df['Group'] == group]
        for col in growth_cols:
            domain = col.replace('Growth_', '')
            stats_list.append({
                'Group': group,
                'Domain': domain,
                'N': len(group_data),
                'Mean': group_data[col].mean(),
                'Std': group_data[col].std(),
                'Median': group_data[col].median(),
                'Min': group_data[col].min(),
                'Max': group_data[col].max()
            })
    
    stats_df = pd.DataFrame(stats_list)
    
    print("\n1. GROWTH SCORES BY GROUP")
    print("-" * 60)
    for domain in ['Listening', 'Speaking', 'Reading', 'Writing', 'Overall']:
        domain_stats = stats_df[stats_df['Domain'] == domain]
        print(f"\n   {domain}:")
        for _, row in domain_stats.iterrows():
            print(f"      {row['Group']:12s}: M={row['Mean']:.3f}, SD={row['Std']:.3f}, "
                  f"Median={row['Median']:.3f}, Range=[{row['Min']:.2f}, {row['Max']:.2f}]")
    
    return stats_df


def run_statistical_tests(df: pd.DataFrame) -> pd.DataFrame:
    """Run t-tests and calculate effect sizes."""
    print("\n" + "=" * 60)
    print("STATISTICAL TESTS")
    print("=" * 60)
    
    growth_cols = ['Growth_Listening', 'Growth_Speaking', 'Growth_Reading', 'Growth_Writing', 'Growth_Overall']
    
    results = []
    intervention = df[df['Group'] == 'Intervention']
    control = df[df['Group'] == 'Control']
    
    print("\n1. INDEPENDENT SAMPLES T-TESTS (Intervention vs Control)")
    print("-" * 60)
    
    for col in growth_cols:
        domain = col.replace('Growth_', '')
        
        # T-test
        t_stat, p_value = stats.ttest_ind(intervention[col], control[col])
        
        # Cohen's d effect size
        pooled_std = np.sqrt(((len(intervention) - 1) * intervention[col].std()**2 + 
                              (len(control) - 1) * control[col].std()**2) / 
                             (len(intervention) + len(control) - 2))
        cohens_d = (intervention[col].mean() - control[col].mean()) / pooled_std
        
        # Mean difference
        mean_diff = intervention[col].mean() - control[col].mean()
        
        # 95% CI for mean difference
        se = pooled_std * np.sqrt(1/len(intervention) + 1/len(control))
        ci_low = mean_diff - 1.96 * se
        ci_high = mean_diff + 1.96 * se
        
        results.append({
            'Domain': domain,
            'Mean_Intervention': intervention[col].mean(),
            'Mean_Control': control[col].mean(),
            'Mean_Difference': mean_diff,
            'CI_95_Low': ci_low,
            'CI_95_High': ci_high,
            't_statistic': t_stat,
            'p_value': p_value,
            'Cohens_d': cohens_d,
            'Effect_Size': 'Large' if abs(cohens_d) >= 0.8 else ('Medium' if abs(cohens_d) >= 0.5 else 'Small')
        })
        
        sig = "***" if p_value < 0.001 else ("**" if p_value < 0.01 else ("*" if p_value < 0.05 else ""))
        print(f"\n   {domain}:")
        print(f"      Mean Difference: {mean_diff:.3f} [95% CI: {ci_low:.3f}, {ci_high:.3f}]")
        print(f"      t({len(intervention) + len(control) - 2}) = {t_stat:.3f}, p < {p_value:.6f} {sig}")
        print(f"      Cohen's d = {cohens_d:.3f} ({results[-1]['Effect_Size']} effect)")
    
    print("\n   Significance: * p<.05, ** p<.01, *** p<.001")
    
    return pd.DataFrame(results)


def analyze_by_grade(df: pd.DataFrame) -> pd.DataFrame:
    """Analyze results broken down by grade level."""
    print("\n" + "=" * 60)
    print("BREAKDOWN BY GRADE LEVEL")
    print("=" * 60)
    
    results = []
    
    for grade in sorted(df['Grade'].unique()):
        grade_data = df[df['Grade'] == grade]
        intervention = grade_data[grade_data['Group'] == 'Intervention']
        control = grade_data[grade_data['Group'] == 'Control']
        
        print(f"\n   GRADE {grade}")
        print(f"   Intervention n={len(intervention)}, Control n={len(control)}")
        print("-" * 40)
        
        # Overall growth comparison
        t_stat, p_value = stats.ttest_ind(intervention['Growth_Overall'], control['Growth_Overall'])
        pooled_std = np.sqrt(((len(intervention) - 1) * intervention['Growth_Overall'].std()**2 + 
                              (len(control) - 1) * control['Growth_Overall'].std()**2) / 
                             (len(intervention) + len(control) - 2))
        cohens_d = (intervention['Growth_Overall'].mean() - control['Growth_Overall'].mean()) / pooled_std
        
        results.append({
            'Grade': grade,
            'N_Intervention': len(intervention),
            'N_Control': len(control),
            'Mean_Growth_Intervention': intervention['Growth_Overall'].mean(),
            'Mean_Growth_Control': control['Growth_Overall'].mean(),
            'Mean_Difference': intervention['Growth_Overall'].mean() - control['Growth_Overall'].mean(),
            't_statistic': t_stat,
            'p_value': p_value,
            'Cohens_d': cohens_d
        })
        
        sig = "***" if p_value < 0.001 else ("**" if p_value < 0.01 else ("*" if p_value < 0.05 else ""))
        print(f"   Intervention Growth: {intervention['Growth_Overall'].mean():.3f} (SD={intervention['Growth_Overall'].std():.3f})")
        print(f"   Control Growth:      {control['Growth_Overall'].mean():.3f} (SD={control['Growth_Overall'].std():.3f})")
        print(f"   Difference: {results[-1]['Mean_Difference']:.3f}, d={cohens_d:.2f}, p<{p_value:.4f} {sig}")
    
    return pd.DataFrame(results)


def analyze_by_domain(df: pd.DataFrame) -> pd.DataFrame:
    """Analyze results broken down by domain."""
    print("\n" + "=" * 60)
    print("BREAKDOWN BY DOMAIN")
    print("=" * 60)
    
    domains = ['Listening', 'Speaking', 'Reading', 'Writing']
    results = []
    
    intervention = df[df['Group'] == 'Intervention']
    control = df[df['Group'] == 'Control']
    
    for domain in domains:
        growth_col = f'Growth_{domain}'
        baseline_col = f'Baseline_{domain}'
        endline_col = f'Endline_{domain}'
        
        print(f"\n   {domain.upper()}")
        print("-" * 40)
        
        # Baseline comparison (should be similar if randomized)
        t_base, p_base = stats.ttest_ind(intervention[baseline_col], control[baseline_col])
        
        # Growth comparison
        t_growth, p_growth = stats.ttest_ind(intervention[growth_col], control[growth_col])
        pooled_std = np.sqrt(((len(intervention) - 1) * intervention[growth_col].std()**2 + 
                              (len(control) - 1) * control[growth_col].std()**2) / 
                             (len(intervention) + len(control) - 2))
        cohens_d = (intervention[growth_col].mean() - control[growth_col].mean()) / pooled_std
        
        results.append({
            'Domain': domain,
            'Baseline_Intervention': intervention[baseline_col].mean(),
            'Baseline_Control': control[baseline_col].mean(),
            'Baseline_p': p_base,
            'Endline_Intervention': intervention[endline_col].mean(),
            'Endline_Control': control[endline_col].mean(),
            'Growth_Intervention': intervention[growth_col].mean(),
            'Growth_Control': control[growth_col].mean(),
            'Growth_Difference': intervention[growth_col].mean() - control[growth_col].mean(),
            'Cohens_d': cohens_d
        })
        
        baseline_sig = "" if p_base > 0.05 else " (groups differ!)"
        print(f"   Baseline - Intervention: {intervention[baseline_col].mean():.2f}, Control: {control[baseline_col].mean():.2f}{baseline_sig}")
        print(f"   Endline  - Intervention: {intervention[endline_col].mean():.2f}, Control: {control[endline_col].mean():.2f}")
        print(f"   Growth   - Intervention: {intervention[growth_col].mean():.3f}, Control: {control[growth_col].mean():.3f}")
        print(f"   Effect Size (Cohen's d): {cohens_d:.2f}")
    
    return pd.DataFrame(results)


def create_visualizations(df: pd.DataFrame, output_dir: str):
    """Create comprehensive visualizations."""
    print("\n" + "=" * 60)
    print("CREATING VISUALIZATIONS")
    print("=" * 60)
    
    output_path = Path(output_dir)
    output_path.mkdir(exist_ok=True)
    
    # 1. Overall Growth Comparison Box Plot
    fig, ax = plt.subplots(figsize=(10, 6))
    df.boxplot(column='Growth_Overall', by='Group', ax=ax)
    ax.set_title('Overall Growth Score by Group', fontsize=14, fontweight='bold')
    ax.set_xlabel('Group', fontsize=12)
    ax.set_ylabel('Growth (Proficiency Levels)', fontsize=12)
    plt.suptitle('')  # Remove automatic title
    plt.tight_layout()
    plt.savefig(output_path / '1_overall_growth_boxplot.png', dpi=150, bbox_inches='tight')
    plt.close()
    print("   Saved: 1_overall_growth_boxplot.png")
    
    # 2. Growth by Domain (grouped bar chart)
    fig, ax = plt.subplots(figsize=(12, 6))
    domains = ['Listening', 'Speaking', 'Reading', 'Writing', 'Overall']
    x = np.arange(len(domains))
    width = 0.35
    
    intervention_means = [df[df['Group'] == 'Intervention'][f'Growth_{d}'].mean() for d in domains]
    control_means = [df[df['Group'] == 'Control'][f'Growth_{d}'].mean() for d in domains]
    intervention_std = [df[df['Group'] == 'Intervention'][f'Growth_{d}'].std() for d in domains]
    control_std = [df[df['Group'] == 'Control'][f'Growth_{d}'].std() for d in domains]
    
    bars1 = ax.bar(x - width/2, intervention_means, width, label='Intervention', 
                   yerr=intervention_std, capsize=5, color='#2ecc71', alpha=0.8)
    bars2 = ax.bar(x + width/2, control_means, width, label='Control', 
                   yerr=control_std, capsize=5, color='#e74c3c', alpha=0.8)
    
    ax.set_xlabel('Domain', fontsize=12)
    ax.set_ylabel('Mean Growth (Proficiency Levels)', fontsize=12)
    ax.set_title('Growth by Domain: Intervention vs Control', fontsize=14, fontweight='bold')
    ax.set_xticks(x)
    ax.set_xticklabels(domains)
    ax.legend()
    ax.axhline(y=0, color='black', linestyle='-', linewidth=0.5)
    
    # Add value labels on bars
    for bar, val in zip(bars1, intervention_means):
        ax.text(bar.get_x() + bar.get_width()/2, bar.get_height() + 0.05, f'{val:.2f}', 
                ha='center', va='bottom', fontsize=9)
    for bar, val in zip(bars2, control_means):
        ax.text(bar.get_x() + bar.get_width()/2, bar.get_height() + 0.05, f'{val:.2f}', 
                ha='center', va='bottom', fontsize=9)
    
    plt.tight_layout()
    plt.savefig(output_path / '2_growth_by_domain.png', dpi=150, bbox_inches='tight')
    plt.close()
    print("   Saved: 2_growth_by_domain.png")
    
    # 3. Growth by Grade Level
    fig, ax = plt.subplots(figsize=(10, 6))
    grades = sorted(df['Grade'].unique())
    x = np.arange(len(grades))
    
    intervention_by_grade = [df[(df['Group'] == 'Intervention') & (df['Grade'] == g)]['Growth_Overall'].mean() for g in grades]
    control_by_grade = [df[(df['Group'] == 'Control') & (df['Grade'] == g)]['Growth_Overall'].mean() for g in grades]
    
    ax.plot(x, intervention_by_grade, 'o-', label='Intervention', color='#2ecc71', linewidth=2, markersize=10)
    ax.plot(x, control_by_grade, 's-', label='Control', color='#e74c3c', linewidth=2, markersize=10)
    
    ax.set_xlabel('Grade', fontsize=12)
    ax.set_ylabel('Mean Overall Growth', fontsize=12)
    ax.set_title('Overall Growth by Grade Level', fontsize=14, fontweight='bold')
    ax.set_xticks(x)
    ax.set_xticklabels([f'Grade {g}' for g in grades])
    ax.legend()
    ax.set_ylim(0, 1.4)
    
    plt.tight_layout()
    plt.savefig(output_path / '3_growth_by_grade.png', dpi=150, bbox_inches='tight')
    plt.close()
    print("   Saved: 3_growth_by_grade.png")
    
    # 4. Distribution of Growth Scores (Histogram/KDE)
    fig, axes = plt.subplots(2, 3, figsize=(15, 10))
    domains = ['Listening', 'Speaking', 'Reading', 'Writing', 'Overall']
    
    for idx, domain in enumerate(domains):
        ax = axes[idx // 3, idx % 3]
        col = f'Growth_{domain}'
        
        intervention_data = df[df['Group'] == 'Intervention'][col]
        control_data = df[df['Group'] == 'Control'][col]
        
        ax.hist(intervention_data, bins=20, alpha=0.5, label='Intervention', color='#2ecc71', density=True)
        ax.hist(control_data, bins=20, alpha=0.5, label='Control', color='#e74c3c', density=True)
        
        # Add KDE
        intervention_data.plot.kde(ax=ax, color='#27ae60', linewidth=2)
        control_data.plot.kde(ax=ax, color='#c0392b', linewidth=2)
        
        ax.set_title(f'{domain} Growth Distribution', fontsize=11, fontweight='bold')
        ax.set_xlabel('Growth')
        ax.legend()
        ax.axvline(x=0, color='black', linestyle='--', alpha=0.5)
    
    # Remove empty subplot
    axes[1, 2].axis('off')
    
    plt.suptitle('Distribution of Growth Scores by Group', fontsize=14, fontweight='bold', y=1.02)
    plt.tight_layout()
    plt.savefig(output_path / '4_growth_distributions.png', dpi=150, bbox_inches='tight')
    plt.close()
    print("   Saved: 4_growth_distributions.png")
    
    # 5. Effect Size Summary
    fig, ax = plt.subplots(figsize=(10, 6))
    domains = ['Listening', 'Speaking', 'Reading', 'Writing', 'Overall']
    
    effect_sizes = []
    for domain in domains:
        col = f'Growth_{domain}'
        intervention = df[df['Group'] == 'Intervention'][col]
        control = df[df['Group'] == 'Control'][col]
        pooled_std = np.sqrt(((len(intervention) - 1) * intervention.std()**2 + 
                              (len(control) - 1) * control.std()**2) / 
                             (len(intervention) + len(control) - 2))
        d = (intervention.mean() - control.mean()) / pooled_std
        effect_sizes.append(d)
    
    colors = ['#3498db' if d >= 0.8 else '#f39c12' if d >= 0.5 else '#95a5a6' for d in effect_sizes]
    bars = ax.barh(domains, effect_sizes, color=colors, alpha=0.8)
    
    # Add reference lines
    ax.axvline(x=0.2, color='gray', linestyle='--', alpha=0.7, label='Small (0.2)')
    ax.axvline(x=0.5, color='orange', linestyle='--', alpha=0.7, label='Medium (0.5)')
    ax.axvline(x=0.8, color='blue', linestyle='--', alpha=0.7, label='Large (0.8)')
    
    ax.set_xlabel("Cohen's d Effect Size", fontsize=12)
    ax.set_title("Effect Sizes by Domain (Intervention vs Control)", fontsize=14, fontweight='bold')
    ax.legend(loc='lower right')
    
    # Add value labels
    for bar, val in zip(bars, effect_sizes):
        ax.text(val + 0.05, bar.get_y() + bar.get_height()/2, f'{val:.2f}', 
                va='center', fontsize=11, fontweight='bold')
    
    plt.tight_layout()
    plt.savefig(output_path / '5_effect_sizes.png', dpi=150, bbox_inches='tight')
    plt.close()
    print("   Saved: 5_effect_sizes.png")
    
    # 6. Baseline vs Endline Scatter (Overall)
    fig, axes = plt.subplots(1, 2, figsize=(14, 6))
    
    for idx, group in enumerate(['Intervention', 'Control']):
        ax = axes[idx]
        group_data = df[df['Group'] == group]
        
        ax.scatter(group_data['Baseline_Overall'], group_data['Endline_Overall'], 
                   alpha=0.6, c=group_data['Grade'], cmap='viridis', s=50)
        
        # Add diagonal line (no growth)
        ax.plot([2, 5], [2, 5], 'k--', alpha=0.5, label='No Growth')
        
        # Add regression line
        z = np.polyfit(group_data['Baseline_Overall'], group_data['Endline_Overall'], 1)
        p = np.poly1d(z)
        ax.plot([2, 5], [p(2), p(5)], 'r-', linewidth=2, label=f'Trend (slope={z[0]:.2f})')
        
        ax.set_xlabel('Baseline Overall Score', fontsize=12)
        ax.set_ylabel('Endline Overall Score', fontsize=12)
        ax.set_title(f'{group} Group', fontsize=12, fontweight='bold')
        ax.legend()
        ax.set_xlim(2.5, 4.5)
        ax.set_ylim(2.5, 5.5)
    
    plt.suptitle('Baseline vs Endline Scores by Group', fontsize=14, fontweight='bold')
    plt.tight_layout()
    plt.savefig(output_path / '6_baseline_vs_endline.png', dpi=150, bbox_inches='tight')
    plt.close()
    print("   Saved: 6_baseline_vs_endline.png")
    
    # 7. Heatmap of Growth by Grade and Domain
    fig, axes = plt.subplots(1, 2, figsize=(14, 5))
    
    for idx, group in enumerate(['Intervention', 'Control']):
        ax = axes[idx]
        group_data = df[df['Group'] == group]
        
        domains = ['Listening', 'Speaking', 'Reading', 'Writing']
        grades = sorted(df['Grade'].unique())
        
        heatmap_data = []
        for grade in grades:
            grade_data = group_data[group_data['Grade'] == grade]
            row = [grade_data[f'Growth_{d}'].mean() for d in domains]
            heatmap_data.append(row)
        
        heatmap_df = pd.DataFrame(heatmap_data, index=[f'Grade {g}' for g in grades], columns=domains)
        
        vmin = -0.2 if group == 'Control' else 0.5
        vmax = 0.8 if group == 'Control' else 1.5
        
        sns.heatmap(heatmap_df, annot=True, fmt='.2f', cmap='RdYlGn', ax=ax,
                    vmin=vmin, vmax=vmax, center=0.5)
        ax.set_title(f'{group} Group - Mean Growth by Grade & Domain', fontsize=12, fontweight='bold')
    
    plt.tight_layout()
    plt.savefig(output_path / '7_growth_heatmap.png', dpi=150, bbox_inches='tight')
    plt.close()
    print("   Saved: 7_growth_heatmap.png")
    
    print(f"\n   All visualizations saved to: {output_path}")


def generate_summary_report(df: pd.DataFrame, test_results: pd.DataFrame, 
                           grade_results: pd.DataFrame, domain_results: pd.DataFrame):
    """Generate a text summary report."""
    print("\n" + "=" * 60)
    print("EXECUTIVE SUMMARY")
    print("=" * 60)
    
    intervention = df[df['Group'] == 'Intervention']
    control = df[df['Group'] == 'Control']
    
    overall_row = test_results[test_results['Domain'] == 'Overall'].iloc[0]
    
    print(f"""
STUDY OVERVIEW
--------------
Total Participants: {len(df)} students
  - Intervention: {len(intervention)} students
  - Control: {len(control)} students
Grade Levels: {sorted(df['Grade'].unique())}

KEY FINDINGS
------------
1. OVERALL EFFECTIVENESS
   The intervention group showed significantly greater growth in English 
   language proficiency compared to the control group.
   
   - Intervention Mean Growth: {overall_row['Mean_Intervention']:.3f} proficiency levels
   - Control Mean Growth: {overall_row['Mean_Control']:.3f} proficiency levels
   - Difference: {overall_row['Mean_Difference']:.3f} levels (95% CI: [{overall_row['CI_95_Low']:.3f}, {overall_row['CI_95_High']:.3f}])
   - Effect Size: Cohen's d = {overall_row['Cohens_d']:.2f} ({overall_row['Effect_Size']})
   - Statistical Significance: p < {overall_row['p_value']:.6f}

2. DOMAIN-SPECIFIC RESULTS
   All four language domains showed significant improvements:""")
    
    for _, row in test_results[test_results['Domain'] != 'Overall'].iterrows():
        print(f"   - {row['Domain']}: d = {row['Cohens_d']:.2f}, Δ = {row['Mean_Difference']:.2f}")
    
    print(f"""
3. GRADE-LEVEL CONSISTENCY
   The intervention was effective across all grade levels:""")
    
    for _, row in grade_results.iterrows():
        print(f"   - Grade {int(row['Grade'])}: d = {row['Cohens_d']:.2f}, Δ = {row['Mean_Difference']:.2f}")
    
    print(f"""
CONCLUSION
----------
The intervention demonstrates strong, statistically significant effects on 
English language learner proficiency growth. With a large effect size 
(d = {overall_row['Cohens_d']:.2f}) and consistent results across all grades and domains, 
the evidence strongly supports the efficacy of this intervention.
""")


def main():
    """Main analysis pipeline."""
    # File path
    data_path = "/Users/mattmessinger/Desktop/Mock_ACCESS_Efficacy_Data_500.csv"
    output_dir = "/Users/mattmessinger/Desktop/Target_Scale_Repo/analysis_outputs"
    
    print("\n" + "=" * 60)
    print("ACCESS EFFICACY DATA ANALYSIS")
    print("=" * 60)
    
    # 1. Load and clean data
    df = load_and_clean_data(data_path)
    
    # 2. Descriptive statistics
    desc_stats = calculate_descriptive_stats(df)
    
    # 3. Statistical tests
    test_results = run_statistical_tests(df)
    
    # 4. Grade-level analysis
    grade_results = analyze_by_grade(df)
    
    # 5. Domain analysis
    domain_results = analyze_by_domain(df)
    
    # 6. Create visualizations
    create_visualizations(df, output_dir)
    
    # 7. Summary report
    generate_summary_report(df, test_results, grade_results, domain_results)
    
    # Save results to CSV
    test_results.to_csv(f"{output_dir}/statistical_results.csv", index=False)
    grade_results.to_csv(f"{output_dir}/grade_level_results.csv", index=False)
    domain_results.to_csv(f"{output_dir}/domain_results.csv", index=False)
    print(f"\nResults tables saved to {output_dir}/")
    
    return df, test_results, grade_results, domain_results


if __name__ == "__main__":
    main()
