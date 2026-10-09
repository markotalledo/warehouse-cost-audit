# Records docs/demo.gif. Regenerate with: vhs docs/demo.tape
Output docs/demo.gif

Set Shell "bash"
Set FontSize 15
Set Width 1440
Set Height 520
Set Padding 24
Set Theme "GitHub Dark"
Set TypingSpeed 25ms

Hide
Type "ln -sf tests/fixtures/snowflake_queries.csv queries.csv && ln -sf tests/fixtures/snowflake_metering.csv metering.csv && export PS1='$ ' && clear"
Enter
Show

Sleep 500ms
Type "uv run costaudit snowflake queries.csv --metering metering.csv --credit-price 3 | head -21"
Sleep 600ms
Enter
Sleep 7s

Hide
Type "rm -f queries.csv metering.csv"
Enter
