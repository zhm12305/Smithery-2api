"""
数据分析工具

提供数据分析和可视化功能。
"""

import io
import json
import base64
from typing import Any, Dict, List, Optional

from .base import BaseTool, ToolError


class DataAnalyzerTool(BaseTool):
    """数据分析工具"""
    
    @property
    def name(self) -> str:
        return "data_analyzer"
    
    @property
    def description(self) -> str:
        return "Analyze data and create visualizations. Supports CSV data, statistical analysis, and chart generation."
    
    @property
    def parameters_schema(self) -> Dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "action": {
                    "type": "string",
                    "enum": ["analyze", "visualize", "statistics", "correlation"],
                    "description": "Type of analysis to perform"
                },
                "data": {
                    "type": "string",
                    "description": "Data in CSV format or JSON array"
                },
                "chart_type": {
                    "type": "string",
                    "enum": ["line", "bar", "scatter", "histogram", "pie"],
                    "description": "Type of chart to create (for visualize action)"
                },
                "x_column": {
                    "type": "string",
                    "description": "X-axis column name (for visualizations)"
                },
                "y_column": {
                    "type": "string",
                    "description": "Y-axis column name (for visualizations)"
                }
            },
            "required": ["action", "data"]
        }
    
    async def execute(self, **kwargs) -> Dict[str, Any]:
        """
        执行数据分析
        
        Args:
            action: 分析类型 (analyze/visualize/statistics/correlation)
            data: 数据 (CSV格式或JSON数组)
            chart_type: 图表类型
            x_column: X轴列名
            y_column: Y轴列名
            
        Returns:
            分析结果
        """
        action = kwargs.get("action")
        data_str = kwargs.get("data")
        
        if not data_str:
            raise ToolError("Data is required")
        
        # 尝试导入必要的库
        try:
            import pandas as pd
            import numpy as np
        except ImportError:
            raise ToolError("pandas and numpy are required for data analysis")
        
        # 解析数据
        try:
            df = self._parse_data(data_str)
        except Exception as e:
            raise ToolError(f"Failed to parse data: {str(e)}")
        
        if action == "analyze":
            return await self._analyze_data(df)
        elif action == "visualize":
            return await self._visualize_data(df, kwargs)
        elif action == "statistics":
            return await self._calculate_statistics(df)
        elif action == "correlation":
            return await self._calculate_correlation(df)
        else:
            raise ToolError(f"Unknown action: {action}")
    
    def _parse_data(self, data_str: str):
        """解析数据"""
        import pandas as pd
        import json

        # 确保输入是字符串
        if not isinstance(data_str, str):
            data_str = str(data_str)

        # 尝试解析为JSON
        try:
            data = json.loads(data_str)
            if isinstance(data, list):
                # 如果是简单的数字列表，转换为DataFrame
                if all(isinstance(x, (int, float)) for x in data):
                    return pd.DataFrame({"value": data})
                else:
                    return pd.DataFrame(data)
            else:
                raise ValueError("JSON data must be an array")
        except json.JSONDecodeError:
            pass

        # 尝试解析为CSV
        try:
            from io import StringIO
            return pd.read_csv(StringIO(data_str))
        except Exception:
            pass

        raise ValueError("Data must be in CSV format or JSON array")
    
    async def _analyze_data(self, df) -> Dict[str, Any]:
        """基本数据分析"""
        import pandas as pd
        
        analysis = {
            "shape": df.shape,
            "columns": list(df.columns),
            "dtypes": df.dtypes.to_dict(),
            "missing_values": df.isnull().sum().to_dict(),
            "memory_usage": df.memory_usage(deep=True).sum(),
            "sample_data": df.head().to_dict('records')
        }
        
        # 数值列的基本统计
        numeric_columns = df.select_dtypes(include=['number']).columns
        if len(numeric_columns) > 0:
            analysis["numeric_summary"] = df[numeric_columns].describe().to_dict()
        
        # 分类列的基本信息
        categorical_columns = df.select_dtypes(include=['object']).columns
        if len(categorical_columns) > 0:
            cat_info = {}
            for col in categorical_columns:
                cat_info[col] = {
                    "unique_count": df[col].nunique(),
                    "top_values": df[col].value_counts().head().to_dict()
                }
            analysis["categorical_summary"] = cat_info
        
        return {
            "action": "analyze",
            "analysis": analysis
        }
    
    async def _visualize_data(self, df, kwargs: Dict[str, Any]) -> Dict[str, Any]:
        """创建数据可视化"""
        try:
            import matplotlib.pyplot as plt
            import matplotlib
            matplotlib.use('Agg')  # 使用非交互式后端
        except ImportError:
            raise ToolError("matplotlib is required for data visualization")
        
        chart_type = kwargs.get("chart_type", "line")
        x_column = kwargs.get("x_column")
        y_column = kwargs.get("y_column")
        
        # 创建图表
        plt.figure(figsize=(10, 6))
        
        if chart_type == "line":
            if x_column and y_column:
                plt.plot(df[x_column], df[y_column])
                plt.xlabel(x_column)
                plt.ylabel(y_column)
            else:
                # 如果没有指定列，绘制所有数值列
                numeric_cols = df.select_dtypes(include=['number']).columns
                for col in numeric_cols[:5]:  # 限制最多5列
                    plt.plot(df.index, df[col], label=col)
                plt.legend()
        
        elif chart_type == "bar":
            if x_column and y_column:
                plt.bar(df[x_column], df[y_column])
                plt.xlabel(x_column)
                plt.ylabel(y_column)
            else:
                # 默认显示数值列的均值
                numeric_cols = df.select_dtypes(include=['number']).columns
                means = df[numeric_cols].mean()
                plt.bar(means.index, means.values)
                plt.xticks(rotation=45)
        
        elif chart_type == "scatter":
            if x_column and y_column:
                plt.scatter(df[x_column], df[y_column])
                plt.xlabel(x_column)
                plt.ylabel(y_column)
            else:
                raise ToolError("Scatter plot requires both x_column and y_column")
        
        elif chart_type == "histogram":
            if y_column:
                plt.hist(df[y_column], bins=20)
                plt.xlabel(y_column)
                plt.ylabel("Frequency")
            else:
                # 默认显示第一个数值列的直方图
                numeric_cols = df.select_dtypes(include=['number']).columns
                if len(numeric_cols) > 0:
                    plt.hist(df[numeric_cols[0]], bins=20)
                    plt.xlabel(numeric_cols[0])
                    plt.ylabel("Frequency")
        
        elif chart_type == "pie":
            if y_column:
                value_counts = df[y_column].value_counts()
                plt.pie(value_counts.values, labels=value_counts.index, autopct='%1.1f%%')
            else:
                raise ToolError("Pie chart requires y_column")
        
        plt.title(f"{chart_type.title()} Chart")
        plt.tight_layout()
        
        # 保存图表为base64编码的图片
        buffer = io.BytesIO()
        plt.savefig(buffer, format='png', dpi=150, bbox_inches='tight')
        buffer.seek(0)
        image_base64 = base64.b64encode(buffer.getvalue()).decode()
        plt.close()
        
        return {
            "action": "visualize",
            "chart_type": chart_type,
            "image_base64": image_base64,
            "image_format": "png"
        }
    
    async def _calculate_statistics(self, df) -> Dict[str, Any]:
        """计算统计信息"""
        import pandas as pd
        
        numeric_columns = df.select_dtypes(include=['number']).columns
        
        if len(numeric_columns) == 0:
            raise ToolError("No numeric columns found for statistical analysis")
        
        stats = {}
        
        for col in numeric_columns:
            col_stats = {
                "count": int(df[col].count()),
                "mean": float(df[col].mean()),
                "median": float(df[col].median()),
                "std": float(df[col].std()),
                "min": float(df[col].min()),
                "max": float(df[col].max()),
                "q25": float(df[col].quantile(0.25)),
                "q75": float(df[col].quantile(0.75)),
                "skewness": float(df[col].skew()),
                "kurtosis": float(df[col].kurtosis())
            }
            stats[col] = col_stats
        
        return {
            "action": "statistics",
            "statistics": stats
        }
    
    async def _calculate_correlation(self, df) -> Dict[str, Any]:
        """计算相关性矩阵"""
        import pandas as pd
        
        numeric_columns = df.select_dtypes(include=['number']).columns
        
        if len(numeric_columns) < 2:
            raise ToolError("At least 2 numeric columns are required for correlation analysis")
        
        correlation_matrix = df[numeric_columns].corr()
        
        return {
            "action": "correlation",
            "correlation_matrix": correlation_matrix.to_dict(),
            "strong_correlations": self._find_strong_correlations(correlation_matrix)
        }
    
    def _find_strong_correlations(self, corr_matrix, threshold=0.7):
        """找出强相关性"""
        import numpy as np
        
        strong_corr = []
        
        for i in range(len(corr_matrix.columns)):
            for j in range(i+1, len(corr_matrix.columns)):
                corr_value = corr_matrix.iloc[i, j]
                if abs(corr_value) >= threshold:
                    strong_corr.append({
                        "column1": corr_matrix.columns[i],
                        "column2": corr_matrix.columns[j],
                        "correlation": float(corr_value)
                    })
        
        return strong_corr
    
    def format_result_for_ai(self, result: Dict[str, Any]) -> str:
        """格式化数据分析结果供AI使用"""
        if not result["success"]:
            return f"Data analysis failed: {result['error']}"
        
        data = result["result"]
        action = data["action"]
        
        if action == "analyze":
            analysis = data["analysis"]
            return f"""Data Analysis Results:
- Shape: {analysis['shape'][0]} rows, {analysis['shape'][1]} columns
- Columns: {', '.join(analysis['columns'])}
- Missing values: {sum(analysis['missing_values'].values())} total
- Memory usage: {analysis['memory_usage']} bytes

Sample data (first 5 rows):
{json.dumps(analysis['sample_data'], indent=2)}"""
        
        elif action == "visualize":
            return f"Chart created successfully: {data['chart_type']} chart (PNG format, base64 encoded)"
        
        elif action == "statistics":
            stats_summary = []
            for col, stats in data["statistics"].items():
                stats_summary.append(f"{col}: mean={stats['mean']:.2f}, std={stats['std']:.2f}, min={stats['min']:.2f}, max={stats['max']:.2f}")
            return f"Statistical Analysis:\n" + "\n".join(stats_summary)
        
        elif action == "correlation":
            strong_corr = data["strong_correlations"]
            if strong_corr:
                corr_text = "\n".join([f"- {item['column1']} ↔ {item['column2']}: {item['correlation']:.3f}" for item in strong_corr])
                return f"Correlation Analysis:\nStrong correlations (|r| ≥ 0.7):\n{corr_text}"
            else:
                return "Correlation Analysis: No strong correlations found (|r| ≥ 0.7)"
        
        return str(data)
