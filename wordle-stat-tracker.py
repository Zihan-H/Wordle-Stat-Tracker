import discord
from discord import app_commands
from discord import ui
import re
import numpy as np
import matplotlib.pyplot as plt
import requests
import datetime as dt
import os

intents = discord.Intents.default()
intents.members = True
intents.guilds = True
intents.message_content = True
client = discord.Client(intents = intents)
tree = app_commands.CommandTree(client)
BASE_LOSS_WEIGHT = 7.5 # it's what NYT decided to use for broad averages: https://www.nytimes.com/2023/12/17/upshot/wordle-bot-year-in-review.html

servers = {}
server = {}
calendar = {}

class WGuild():
    def __init__(self, gid, gname, owner):
        self.gid = gid
        self.gname = gname
        self.owner = owner
        self.BASE_LOSS_WEIGHT = 7.5
        self.server = {}
        self.calendar = {}
        self.par_Q1 = 0
        self.par_Q2 = 0
        self.par_Q3 = 0
        self.par_mean = 0

    def set_BASE_LOSS_WEIGHT(self, BASE_LOSS_WEIGHT):
        self.BASE_LOSS_WEIGHT = BASE_LOSS_WEIGHT

class Player:
    def __init__(self, pid, pname):
        self.pid = pid
        self.pname = pname
        self.scores = np.resize(np.array([[]]), (0, 3))
        self.crowns = 0
        self.losses = 0
        self.currstreak = 0
        self.maxstreak = 0
        self.numgames = 0

    def __repr__(self):
        return str(self.pname) + str(self.scores)

    def addStreak(self):
        self.currstreak += 1
        if (self.currstreak > self.maxstreak):
            self.maxstreak = self.currstreak

    def updateScores(self, score, crown, date):
        if crown:
            self.crowns += 1
        if score == 'X':
            self.losses += 1
        elif len(self.scores) == 0:
            self.addStreak()
        elif self.scores[len(self.scores) - 1][2] == (date - dt.timedelta(days = 1)):
            self.addStreak()
        else:
            self.currstreak = 1
        self.numgames += 1
        self.scores = np.append(self.scores, [[score, crown, date]], axis = 0)
        
    def getGamesPlayed(self):
        return len(self.scores) + self.losses
        
class Day:    
    def __init__(self, date, leaderboard, channel, numPlayers, par, image):
        self.date = date
        wordle = requests.get(f"https://www.nytimes.com/svc/wordle/v2/{date:%Y-%m-%d}.json").json()
        self.word = wordle['solution']
        self.wordlenum = wordle['days_since_launch']
        self.leaderboard = leaderboard
        self.channel = channel
        self.numPlayers = numPlayers
        self.par = par
        self.image = image

    def __repr__(self):
        return self.word + ' ' + str(self.date) + ' ' + str(self.leaderboard)

    def mergeLeaderboard(self, newboard, wguild):
        server = wguild.server
        newsum = self.par * self.numPlayers
        for row in range(len(newboard[:, 0])):
            i = 0
            while newboard[row][0] > self.leaderboard[i][0]:
                i += 1
            if newboard[row][0] != self.leaderboard[i][0]:
                if i == 0:
                    for col in self.leaderboard[0][1:]:
                        pid = col.strip()
                        player = server[pid]
                        index = list(player.scores[:, 2]).index(self.date)
                        player.scores[index][1] = False
                        player.crowns -= 1
                self.numPlayers += list(newboard[row]).index(0) - 1
                newsum += newboard[row][0] * (list(newboard[row]).index(0) - 1)
                self.leaderboard = np.insert(self.leaderboard, i, newboard[row], axis = 0)
            else:
                for col in newboard[row][1:list(newboard[row]).index(0)]:
                    self.numPlayers += 1
                    self.newsum += newboard[row][0]
                    self.leaderboard[i][list(self.leaderboard[i]).index(0)] = col
        self.par = newsum / self.numPlayers
            
        
# [3 Ernest 0 0 0 0 0 0 0 0 0 0 0 0 ...]
# [4 Noah Nathan Rory Michael 0 0 0 ...]
# [5 Zihan 0 0 0 0 0 0 0 0 0 0 0 0  ...]
# [6 Shaan 0 0 0 0 0 0 0 0 0 0 0 0  ...]

def ripScores(raw, date, wguild):
    server = wguild.server
    BASE_LOSS_WEIGHT = wguild.BASE_LOSS_WEIGHT
    scores = np.resize(np.array([[]]), (0, len(server) + 1))
    score = ''
    players = []
    scorers = []
    total = 0
    for line in raw.split('\n'):
        crown = False
        if '@' in line:
            if '👑' in line:
                crown = True
            score = line[line.index('/') - 1]
            for pid in line.split('@')[1:]:
                pid = int(pid[:-1])
                players += [pid]
                scorers += [pid]
                if score != 'X':
                    total += int(score)
                else:
                    total += BASE_LOSS_WEIGHT
                player = server[pid]
                player.updateScores(score, crown, date)
            scores = np.append(scores, [[score] + scorers + [0 for i in range(len(server) - len(scorers))]], axis = 0)
            scorers = []
    return (scores, len(players), total)
                
                
    
#Your group is on a 415 day streak! 🔥🔥🔥 Here are yesterday's results:
#👑 3/6: @Ernest
#4/6: @Noah @Nathan @Rory @Michael
#5/6: @Zihan
#6/6: @Shaan

async def prep_guild(guild):
    wguild = servers[guild.id]
    server = wguild.server
    calendar = wguild.calendar
    for member in guild.members:
        if not(member.bot):
            server[member.id] = Player(member.id, member.nick)
    print("server loaded")
    for channel in guild.channels:
        if (type(channel) != discord.channel.CategoryChannel):
            async for message in channel.history(limit = None):
                if (message.author.id == 1211781489931452447) & ('👑' in message.content):
                    date = message.created_at.date() - dt.timedelta(days = 1)
                    check = calendar.get(date)
                    if check == None:
                        rip = ripScores(message.content, date, wguild)
                        scores = rip[0]
                        numPlayers = rip[1]
                        par = rip[2] / numPlayers
                        calendar[date] = Day(date, scores, channel, numPlayers, par, message.attachments[0].url)
                    elif channel == check.channel:
                        date = message.created_at.date()
                        rip = ripScores(message.content, date, wguild)
                        scores = rip[0]
                        numPlayers = rip[1]
                        par = rip[2] / numPlayers
                        calendar[date] = Day(date, scores, channel, numPlayers, par, message.attachments[0].url)
                    else:
                        newboard = ripScores(message.content, date, wguild)[0]
                        calendar[date].mergeLeaderboard(newboard, wguild)
    print("messages loaded")
    for pid in server:
        server[pid].scores = server[pid].scores[server[pid].scores[:, 2].argsort()[::-1]]
    pardata = np.array([calendar[day].par for day in calendar])
    wguild.par_Q1 = np.quantile(pardata, 0.25)
    wguild.par_Q2 = np.median(pardata)
    wguild.par_Q3 = np.quantile(pardata, 0.75)
    wguild.par_mean = np.mean(pardata)
    return

@client.event
async def on_ready():
    await tree.sync()
    print(f'We have logged in as {client.user}')
    for guild in client.guilds:
        wguild = WGuild(guild.id, guild.name, guild.owner)
        servers[guild.id] = wguild
        await prep_guild(guild)
    return  

class HistoryView(ui.LayoutView):
    crowncol = "[1;33m"
    goodcol = "[2;32m"
    badcol = "[2;31m"

    box = ui.Container()
    acrow = ui.ActionRow()
    
    def __init__(self, scores, header, emoji, calendar):
        super().__init__()
        self.scores = scores
        self.page = 0
        self.header = header
        self.emoji = emoji
        self.calendar = calendar
        self.numpages = int(np.ceil(len(scores) / 10)) - 1
        if self.numpages < 0:
            self.numpages = 0
        if self.numpages == 0:
            self.acrow.children[2].disabled = True
        self.acrow.children[1].label = f"Page {(self.page + 1)} / {(self.numpages + 1)}"
        self.box.accent_colour = discord.Colour.teal()
        self.box.add_item(ui.TextDisplay(header))
        self.fillbox(self.box, self.page, self.scores, self.emoji, self.calendar)

    @classmethod
    def fillbox(self, box, page, scores, emoji, calendar):
        for i in range(10 * page, min(10 * (page + 1), len(scores))):
            row = scores[i]
            data = "```ansi\n "
            data += "%s: " % str(i + 1).zfill(int(np.log10(len(scores))) + 1)
            day = calendar[row[2]]
            data += row[2].isoformat()
            data += " |   "
            data += str(day.wordlenum).zfill(4)
            data += "   |  "
            data += calendar[row[2]].word.upper()
            data += "  |   "
            if row[1]:
                data += HistoryView.crowncol
            elif int(row[0]) <= day.par:
                data += HistoryView.goodcol
            else:
                data += HistoryView.badcol
            data += row[0]
            data += "[0m"
            data += "   | "
            data += "%.3f ```" % day.par
            box.add_item(ui.TextDisplay(data))
            box.add_item(ui.Separator())

    @acrow.button(label = "Previous", style = discord.ButtonStyle.primary, disabled = True)
    async def prev(self, interaction: discord.Interaction, button: ui.Button):
        self.page -= 1
        self.acrow.children[1].label = f"Page {(self.page + 1)} / {(self.numpages + 1)}"
        self.acrow.children[2].disabled = False
        if self.page == 0:
            self.acrow.children[0].disabled = True
        self.box.clear_items()
        self.clear_items()
        self.box.add_item(ui.TextDisplay(self.header))
        self.fillbox(self.box, self.page, self.scores, self.emoji, self.calendar)
        self.add_item(self.box)
        self.add_item(self.acrow)
        await interaction.response.edit_message(view = self)

    @acrow.button(label = "filler", style = discord.ButtonStyle.secondary, disabled = True)
    async def nothing(self, interaction: discord.Interaction, button: ui.Button):
        return

    @acrow.button(label = "Next", style = discord.ButtonStyle.primary, disabled = False)
    async def next(self, interaction: discord.Interaction, button: ui.Button):
        self.page += 1
        self.acrow.children[1].label = f"Page {(self.page + 1)} / {(self.numpages + 1)}"
        self.acrow.children[0].disabled = False
        if self.page == self.numpages:
            self.acrow.children[2].disabled = True
        self.box.clear_items()
        self.clear_items()
        self.box.add_item(ui.TextDisplay(self.header))
        self.fillbox(self.box, self.page, self.scores, self.emoji, self.calendar)
        self.add_item(self.box)
        self.add_item(self.acrow)
        await interaction.response.edit_message(view = self)
        
class CrownLossView(HistoryView):
    def __init__(self, scores, header, emoji, calendar):
        super().__init__(scores, header, emoji, calendar)
        if emoji == '👑':
            self.box.accent_colour = discord.Colour.gold()
        elif emoji == '❌':
            self.box.accent_colour = discord.Colour.red()

    @classmethod
    def fillbox(self, box, page, scores, emoji, calendar):
        box.add_item(ui.Separator())
        for i in range(10 * page, min(10 * (page + 1), len(scores))):
            row = scores[i]
            data = "``` "
            data += "%s: " % str(i + 1).zfill(int(np.log10(len(scores))) + 1)
            data += emoji + " "
            data += str(row[2]) + " "
            data += calendar[row[2]].word.upper() + " "
            data += "%s/6 (Par %.3f)" % (row[0], calendar[row[2]].par)
            data += " ```"
            box.add_item(ui.TextDisplay(data))
            box.add_item(ui.Separator())

@tree.command(name = "history", description = "[player]'s last [x {default: 10}] Wordles since [start: {format: YYYY-MM-DD, default: today}}]")
async def history(interaction: discord.Interaction, player: discord.Member, x: int | None, start: str | None):
    wguild = servers[interaction.guild_id]
    server = wguild.server
    calendar = wguild.calendar
    view = ui.LayoutView()
    if x == None:
        x = 10
    if x < 1:
        box = ui.Container(accent_colour = discord.Colour.magenta())
        box.add_item(ui.TextDisplay("Invalid x"))
        view.add_item(box)
        await interaction.response.send_message(view = view, ephemeral = True, delete_after = 15)
        return
    try:
        start = dt.date.fromisoformat(start)
    except(ValueError, TypeError):
        if start == None:
            start = dt.date.today()
        else:
            box = ui.Container(accent_colour = discord.Colour.magenta())
            box.add_item(ui.TextDisplay("Invalid start date"))
            view.add_item(box)
            await interaction.response.send_message(view = view, ephemeral = True, delete_after = 15)
            return
    if player.id not in server:
        box = ui.Container(accent_colour = discord.Colour.magenta())
        box.add_item(ui.TextDisplay("Invalid player"))
        view.add_item(box)
        await interaction.response.send_message(view = view, ephemeral = True, delete_after = 15)
        return
    pid = player.id
    if x == 401:
        x = 70
        pid = 1
    elif x == 402:
        x = 70
        pid = 2
    scores = server[pid].scores[server[pid].scores[:, 2] <= start]
    scores = scores[scores[:, 2].argsort()[::-1]]
    view = HistoryView(scores[:x], "```" + " " * (int(np.log10(len(scores)) + 2)) + "     Date    | Wordle # |  Word   | Score |  Par ```", '', calendar)
    await interaction.response.send_message(view = view, ephemeral = True)
    return

@tree.command(name = "line", description = "Line graph for [player] from [start {default: oldest Wordle}] to [end {default: most recent Wordle}]")
@app_commands.describe(start = "format: YYYY-MM-DD", end = "format: YYYY-MM-DD")
async def line(interaction: discord.Interaction, player: discord.Member, start: str | None, end: str | None):
    server = servers[interaction.guild_id].server
    view = ui.LayoutView()
    if player.id not in server:
        box = ui.Container(accent_colour = discord.Colour.magenta())
        box.add_item(ui.TextDisplay("Invalid player"))
        view.add_item(box)
        await interaction.response.send_message(view = view, ephemeral = True, delete_after = 15)
        return
    try:
        start = dt.date.fromisoformat(start)
    except(ValueError, TypeError):
        if start == None:
            start = dt.date(2000, 1, 1)
        else:
            box = ui.Container(accent_colour = discord.Colour.magenta())
            box.add_item(ui.TextDisplay("Invalid start date"))
            view.add_item(box)
            await interaction.response.send_message(view = view, ephemeral = True, delete_after = 15)
            return
    try:
        end = dt.date.fromisoformat(end)
    except(ValueError, TypeError):
        if end == None:
            end = dt.date.today()
        else:
            box = ui.Container(accent_colour = discord.Colour.magenta())
            box.add_item(ui.TextDisplay("Invalid end date"))
            view.add_item(box)
            await interaction.response.send_message(view = view, ephemeral = True, delete_after = 15)
            return
    player = server[player.id]
    data = player.scores[player.scores[:, 2] >= start]
    data = data[data[:, 2] <= end]
    losses = data[data[:, 0] == 'X']
    data = data[data[:, 0] != 'X']
    data[:, 0] = np.array([int(i) for i in data[:, 0]])
    crowns = data[data[:, 1] == True]
    for date in np.arange(data[-1][2], (data[0][2] + dt.timedelta(days = 1))):
        for i in range(len(data)):
            if data[i][2] == date:
                break
            elif data[i][2] < date:
                data = np.insert(data, i, np.array([None, None, date]), axis = 0)
                break
    fig = plt.figure()
    ax = fig.add_subplot()
    ax.plot(np.arange(data[-1][2], (data[0][2] + dt.timedelta(days = 1))), data[:, 0])
    ax.scatter(crowns[:, 2], crowns[:, 0], c = 'xkcd:gold', marker = '*')
    ax.scatter(losses[:, 2], [BASE_LOSS_WEIGHT for i in losses], c = 'xkcd:crimson', marker = 'X')
    ax.set_yticks(np.array([BASE_LOSS_WEIGHT, 6, 5, 4, 3, 2, 1, 0]), ['X', '6', '5', '4', '3', '2', '1', '0'])
    ax.set_xlabel("Date")
    ax.tick_params(axis = 'x', labelrotation = 90)
    ax.set_ylabel("Score")
    ax.set_title(player.pname)
    fig.savefig("%s.png" % str(player.pid), bbox_inches = "tight")
    await interaction.response.send_message(file = discord.File("%s.png" % str(player.pid)), ephemeral = True)
    os.remove("%s.png" % str(player.pid))
    return

@tree.command(name = "bar", description = "Bar chart for [player] from [start {default: oldest Wordle}] to [end {default: most recent Wordle}]")
@app_commands.describe(start = "format: YYYY-MM-DD", end = "format: YYYY-MM-DD")
async def bar(interaction: discord.Interaction, player: discord.Member, start: str | None, end: str | None):
    server = servers[interaction.guild_id].server
    view = ui.LayoutView()
    if player.id not in server:
        box = ui.Container(accent_colour = discord.Colour.magenta())
        box.add_item(ui.TextDisplay("Invalid player"))
        view.add_item(box)
        await interaction.response.send_message(view = view, ephemeral = True, delete_after = 15)
        return
    try:
        start = dt.date.fromisoformat(start)
    except(ValueError, TypeError):
        if start == None:
            start = dt.date(2000, 1, 1)
        else:
            box = ui.Container(accent_colour = discord.Colour.magenta())
            box.add_item(ui.TextDisplay("Invalid start date"))
            view.add_item(box)
            await interaction.response.send_message(view = view, ephemeral = True, delete_after = 15)
            return
    try:
        end = dt.date.fromisoformat(end)
    except(ValueError, TypeError):
        if end == None:
            end = dt.date.today()
        else:
            box = ui.Container(accent_colour = discord.Colour.magenta())
            box.add_item(ui.TextDisplay("Invalid end date"))
            view.add_item(box)
            await interaction.response.send_message(view = view, ephemeral = True, delete_after = 15)
            return
    player = server[player.id]
    data = player.scores[player.scores[:, 2] >= start]
    data = data[data[:, 2] <= end]
    numones = len(data[data[:, 0] == '1'])
    numtwos = len(data[data[:, 0] == '2'])
    numthrees = len(data[data[:, 0] == '3'])
    numfours = len(data[data[:, 0] == '4'])
    numfives = len(data[data[:, 0] == '5'])
    numsixes = len(data[data[:, 0] == '6'])
    fig = plt.figure()
    ax = fig.add_subplot()
    bars = ax.bar(['1', '2', '3', '4', '5', '6', 'X'], [numones, numtwos, numthrees, numfours, numfives, numsixes, player.losses])
    ax.set_xlabel = "Score"
    ax.set_ylabel = "Frequency"
    ax.set_yticks(range(0, max([numones, numtwos, numthrees, numfours, numfives, numsixes, player.losses]) + 1, 1))
    ax.set_title(player.pname)
    bars.patches[-1].set(color = "xkcd:crimson")
    fig.savefig("%s.png" % str(player.pid))
    await interaction.response.send_message(file = discord.File("%s.png" % str(player.pid)), ephemeral = True)
    os.remove("%s.png" % str(player.pid))
    return

@tree.command(name = "crowns", description = "Number of times [player] got top score on the Wordle")
async def crowns(interaction: discord.Interaction, player: discord.Member, secret: int | None):
    server = servers[interaction.guild_id].server
    calendar = servers[interaction.guild_id].calendar
    if player.id not in server:
        view = ui.LayoutView()
        box = ui.Container(accent_colour = discord.Colour.magenta())
        box.add_item(ui.TextDisplay("Invalid player"))
        view.add_item(box)
        await interaction.response.send_message(view = view, ephemeral = True, delete_after = 15)
        return
    pid = player.id
    if secret != None:
        pid = secret
    view = CrownLossView(server[pid].scores[list(server[pid].scores[:, 1])], f"You have won {server[pid].crowns} crowns:", '👑', calendar)
    await interaction.response.send_message(view = view, ephemeral = True)
    return

@tree.command(name = "fails", description = "Number of times [player] failed to solve the Wordle")
async def fails(interaction: discord.Interaction, player: discord.Member, secret: int | None):
    server = servers[interaction.guild_id].server
    calendar = servers[interaction.guild_id].calendar
    if player.id not in server:
        view = ui.LayoutView()
        box = ui.Container(accent_colour = discord.Colour.magenta())
        box.add_item(ui.TextDisplay("Invalid player"))
        view.add_item(box)
        await interaction.response.send_message(view = view, ephemeral = True, delete_after = 15)
        return
    pid = player.id
    if secret != None:
        pid = secret
    view = CrownLossView(server[pid].scores[server[pid].scores[:, 0] == 'X'], f"{player.nick} has failed to solve {server[pid].losses} Wordles:", '❌', calendar)
    await interaction.response.send_message(view = view, ephemeral = True)
    return

@tree.command(name = "solved", description = "Number of times [player] solved the Wordle")
async def solved(interaction: discord.Interaction, player: discord.Member):
    server = servers[interaction.guild_id].server
    view = ui.LayoutView()
    if player.id not in server:
        box = ui.Container(accent_colour = discord.Colour.magenta())
        box.add_item(ui.TextDisplay("Invalid player"))
        view.add_item(box)
        await interaction.response.send_message(view = view, ephemeral = True, delete_after = 15)
        return
    box = ui.Container(ui.TextDisplay(f"{player.nick} has solved {(server[player.id].numgames - server[player.id].losses)} Wordles"), accent_colour = discord.Colour.brand_green())
    view.add_item(box)
    await interaction.response.send_message(view = view, ephemeral = True)
    return

@tree.command(name = "games_played", description = "Number of times [player] played the Wordle")
async def games_played(interaction: discord.Interaction, player: discord.Member):
    server = servers[interaction.guild_id].server
    view = ui.LayoutView()
    if player.id not in server:
        box = ui.Container(accent_colour = discord.Colour.magenta())
        box.add_item(ui.TextDisplay("Invalid player"))
        view.add_item(box)
        await interaction.response.send_message(view = view, ephemeral = True, delete_after = 15)
        return
    box = ui.Container(ui.TextDisplay(f"{player.nick} has played {server[player.id].numgames} Wordles"), accent_colour = discord.Colour.purple())
    view.add_item(box)
    await interaction.response.send_message(view = view, ephemeral = True)
    return

@tree.command(name = "crown_rate", description = "% of all played Wordles where [player] won a crown")
async def crown_rate(interaction: discord.Interaction, player: discord.Member):
    server = servers[interaction.guild_id].server
    view = ui.LayoutView()
    if player.id not in server:
        box = ui.Container(accent_colour = discord.Colour.magenta())
        box.add_item(ui.TextDisplay("Invalid player"))
        view.add_item(box)
        await interaction.response.send_message(view = view, ephemeral = True, delete_after = 15)
        return
    box = ui.Container(ui.TextDisplay("%s has earned a crown in %.2f%% Wordles" % (player.nick, 100 * (server[player.id].crowns / server[player.id].numgames))), accent_colour = discord.Colour.gold())
    view.add_item(box)
    await interaction.response.send_message(view = view, ephemeral = True)
    return

@tree.command(name = "fail_rate", description = "% of all played Wordles [player] failed to solve")
async def fail_rate(interaction: discord.Interaction, player: discord.Member):
    server = servers[interaction.guild_id].server
    view = ui.LayoutView()
    if player.id not in server:
        box = ui.Container(accent_colour = discord.Colour.magenta())
        box.add_item(ui.TextDisplay("Invalid player"))
        view.add_item(box)
        await interaction.response.send_message(view = view, ephemeral = True, delete_after = 15)
        return
    box = ui.Container(ui.TextDisplay("%s has failed to solve %.2f%% of their Wordles" % (player.nick, 100 * (server[player.id].losses / server[player.id].numgames))), accent_colour = discord.Colour.red())
    view.add_item(box)
    await interaction.response.send_message(view = view, ephemeral = True)
    return

@tree.command(name = "average", description = "[player]'s average score over the last [x {default: all solved<OPT: played> Wordles}] Wordles")
@app_commands.describe(losses = "<OPT: if losses = True, includes losses scored with the server's BASE_LOSS_WEIGHT>")
async def average(interaction: discord.Interaction, player: discord.Member, x: int | None, losses: bool | None):
    server = servers[interaction.guild_id].server
    BASE_LOSS_WEIGHT = servers[interaction.guild_id].BASE_LOSS_WEIGHT
    view = ui.LayoutView()
    if player.id not in server:
        box = ui.Container(accent_colour = discord.Colour.magenta())
        box.add_item(ui.TextDisplay("Invalid player"))
        view.add_item(box)
        await interaction.response.send_message(view = view, ephemeral = True, delete_after = 15)
        return
    raw = server[player.id].scores[:, 0]
    scores = []
    if losses == None:
        scores = [int(score) for score in raw[raw != 'X']]
        if len(scores) == 0:
            box = ui.Container(ui.TextDisplay("Go solve more Wordles, buddy"), accent_colour = discord.Colour.red())
            view.add_item(box)
            await interaction.response.send_message(view = view, ephemeral = True, delete_after = 15)
            return
    else:
        for score in raw:
            if score == 'X':
                scores += [BASE_LOSS_WEIGHT]
            else:
                scores += [int(score)]
    if x == None:
        x = len(scores)
    if x <= 0:
        box = ui.Container(ui.TextDisplay("Invalid x"), accent_colour = discord.Colour.red())
        view.add_item(box)
        await interaction.response.send_message(view = view, ephemeral = True, delete_after = 15)
        return
    average = sum(scores[:x]) / x
    box = ui.Container(ui.TextDisplay("%s has an average Wordle score of %.2f, %s" % (player.nick, average, "excluding losses." if (losses == None) else "including losses as a score of %.2f / 6" % BASE_LOSS_WEIGHT)), accent_colour = discord.Colour.teal())    
    view.add_item(box)
    await interaction.response.send_message(view = view, ephemeral = True)
    return

@tree.command(name = "current_streak", description = "[player]'s current Wordle solving streak")
async def current_streak(interaction: discord.Interaction, player: discord.Member):
    server = servers[interaction.guild_id].server
    if player.id not in server:
        view = ui.LayoutView()
        box = ui.Container(accent_colour = discord.Colour.magenta())
        box.add_item(ui.TextDisplay("Invalid player"))
        view.add_item(box)
        await interaction.response.send_message(view = view, ephemeral = True, delete_after = 15)
        return
    box = ui.Container(ui.TextDisplay("%s currently has a %i Wordle solving streak" % (player.nick, server[player.id].currstreak)), accent_colour = discord.Colour.orange())
    view = ui.LayoutView()
    view.add_item(box)
    await interaction.response.send_message(view = view, ephemeral = True)
    return

@tree.command(name = "best_streak", description = "[player]'s all time best Wordle solving streak")
async def best_streak(interaction: discord.Interaction, player: discord.Member):
    server = servers[interaction.guild_id].server
    view = ui.LayoutView()
    if player.id not in server:
        box = ui.Container(accent_colour = discord.Colour.magenta())
        box.add_item(ui.TextDisplay("Invalid player"))
        view.add_item(box)
        await interaction.response.send_message(view = view, ephemeral = True, delete_after = 15)
        return
    box = ui.Container(ui.TextDisplay("%s's all time best Wordle streak %s %i %s long" % (player.nick, ("is ongoing and currently" if (server[player.id].currstreak == server[player.id].maxstreak) else "was"), server[player.id].maxstreak, ("day" if (server[player.id].maxstreak == 1) else "days"))), accent_colour = discord.Colour.orange())
    view.add_item(box)
    await interaction.response.send_message(view = view, ephemeral = True)
    return

# Date:
# Word: 
# Par (Difficulty [based on quartiles of all time par data]):
# Observed vs Expected scores:

async def local_summary(interaction, date):
    wguild = servers[interaction.guild_id]
    server = wguild.server
    calendar = wguild.calendar
    BASE_LOSS_WEIGHT = wguild.BASE_LOSS_WEIGHT
    view = ui.LayoutView()
    try:
        date = dt.date.fromisoformat(date)
    except(ValueError):
        box = ui.Container(accent_colour = discord.Colour.magenta())
        box.add_item(ui.TextDisplay("No recorded Wordle on given date"))
        view.add_item(box)
        await interaction.response.send_message(view = view, ephemeral = True, delete_after = 15)
        return
    day = calendar[date]
    data = date.strftime("%A, %B %d, %Y")
    data += "\nWord: %s" % day.word
    data += "\nPar %.2f (Difficulty: %s)\n\n👑 " % (day.par, ("Easy" if day.par <= wguild.par_Q1 else "Medium" if day.par <= wguild.par_Q3 else "Hard"))
    for row in day.leaderboard:
        row = np.append(row[np.nonzero(row)], ['0'])
        data +=  row[0] + " / 6:  " 
        for pid in row[1:]:
            pid = int(pid)
            data += server[pid].pname
            total = 0
            for score in server[pid].scores[:, 0]:
                if score == 'X':
                    total += BASE_LOSS_WEIGHT
                else:
                    total += int(score)
            average = total / len(server[pid].scores[:, 0])
            data += " [Expected: %.2f]" % (average * (day.par / wguild.par_mean))
            if row[list(row).index(str(pid)) + 1] != '0':
                data += ", "
            else:
                break
        data += "\n"
    box = ui.Section(data, accessory = ui.Thumbnail(media = day.image))
    cont = ui.Container(box, accent_colour = discord.Colour.blurple())
    view.add_item(cont)
    await interaction.response.send_message(view = view, ephemeral = True)
    return

@tree.command(name = "summary", description = "Summary info on [date {format: YYYY-MM-DD}]'s Wordle")
async def summary(interaction: discord.Interaction, date: str):
    await local_summary(interaction, date)

@tree.command(name = "hardest", description = "Hardest of the last [x {default: all Wordles}] Wordles with [at_least {default: 1}] players")
async def hardest(interaction: discord.Interaction, x: int | None, at_least: int | None):
    calendar = servers[interaction.guild_id].calendar
    view = ui.LayoutView()
    if x == None:
        x = len(calendar)
    elif x <= 0:
        box = ui.Container(ui.TextDisplay("Invalid x"), accent_colour = discord.Colour.red())
        view.add_item(box)
        await interaction.response.send_message(view = view, ephemeral = True, delete_after = 15)
        return
    if at_least == None:
        at_least = 1
    elif at_least <= 0:
        box = ui.Container(ui.TextDisplay("Invalid at_least"), accent_colour = discord.Colour.red())
        view.add_item(box)
        await interaction.response.send_message(view = view, ephemeral = True, delete_after = 15)
        return
    maxpar = -1
    maxdate = None
    wordles = np.array([list(calendar.keys()), list(calendar.values())]).T
    wordles = wordles[wordles[:, 0].argsort()[::-1]]
    for row in wordles[:x]:
        wordle = row[1]
        if wordle.numPlayers >= at_least:
            if wordle.par > maxpar:
                maxdate = wordle.date
                maxpar = wordle.par
    if maxdate == None:
        box = ui.Container(ui.TextDisplay("No Wordle in the server meets the condition of having at least %i players" % at_least), accent_colour = discord.Colour.red())
        view.add_item(box)
        await interaction.response.send_message(view = view, ephemeral = True, delete_after = 15)
        return
    await local_summary(interaction, maxdate.isoformat())
    return

@tree.command(name = "easiest", description = "Easiest of the last [x {default: all Wordles}] Wordles with [at_least {default: 1}] players")
async def easiest(interaction: discord.Interaction, x: int | None, at_least: int | None):
    calendar = servers[interaction.guild_id].calendar
    view = ui.LayoutView()
    if x == None:
        x = len(calendar)
    elif x <= 0:
        box = ui.Container(ui.TextDisplay("Invalid x"), accent_colour = discord.Colour.red())
        view.add_item(box)
        await interaction.response.send_message(view = view, ephemeral = True, delete_after = 15)
        return
    if at_least == None:
        at_least = 1
    elif at_least <= 0:
        box = ui.Container(ui.TextDisplay("Invalid at_least"), accent_colour = discord.Colour.red())
        view.add_item(box)
        await interaction.response.send_message(view = view, ephemeral = True, delete_after = 15)
        return
    minpar = 999
    mindate = None
    wordles = np.array([list(calendar.keys()), list(calendar.values())]).T
    wordles = wordles[wordles[:, 0].argsort()[::-1]]
    for row in wordles[:x]:
        wordle = row[1]
        if wordle.numPlayers >= at_least:
            if wordle.par < minpar:
                mindate = wordle.date
                minpar = wordle.par
    if mindate == None:
        box = ui.Container(ui.TextDisplay("No Wordle in the server meets the condition of having at least %i players" % at_least), accent_colour = discord.Colour.red())
        view.add_item(box)
        await interaction.response.send_message(view = view, ephemeral = True, delete_after = 15)
        return
    await local_summary(interaction, mindate.isoformat())
    return

@tree.command(name = "par_line", description = "Line graph of pars from [start {default: oldest Wordle}] to [end {default: most recent Wordle}]")
@app_commands.describe(start = "format: YYYY-MM-DD", end = "format: YYYY-MM-DD")
async def par_line(interaction: discord.Interaction, start: str | None, end: str | None):
    calendar = servers[interaction.guild_id].calendar
    view = ui.LayoutView()
    try:
        start = dt.date.fromisoformat(start)
    except(ValueError, TypeError):
        if start == None:
            start = min(list(calendar.keys()))
        else:
            box = ui.Container(accent_colour = discord.Colour.magenta())
            box.add_item(ui.TextDisplay("Invalid start date"))
            view.add_item(box)
            await interaction.response.send_message(view = view, ephemeral = True, delete_after = 15)
            return
    try:
        end = dt.date.fromisoformat(end)
    except(ValueError, TypeError):
        if end == None:
            end = max(list(calendar.keys()))
        else:
            box = ui.Container(accent_colour = discord.Colour.magenta())
            box.add_item(ui.TextDisplay("Invalid end date"))
            view.add_item(box)
            await interaction.response.send_message(view = view, ephemeral = True, delete_after = 15)
            return
    data = []
    for date in np.arange(start, end + dt.timedelta(days = 1)):
        date = dt.date.fromisoformat(str(date))
        if date in calendar:
            data += [calendar[date].par]
        else:
            data += [None]
    data = np.array(data)
    fig = plt.figure()
    ax = fig.add_subplot()
    ax.plot(np.arange(start, end + dt.timedelta(days = 1)), data)
    ax.scatter(np.arange(start, end + dt.timedelta(days = 1)), data)
    ax.set_ylabel("Par")
    ax.set_xlabel("Date")
    ax.set_yticks(np.arange(0, 6.1, 1))
    ax.tick_params(axis = 'x', labelrotation = 90)
    fig.savefig("par-overview.png", bbox_inches = "tight")
    await interaction.response.send_message(file = discord.File("par-overview.png"), ephemeral = True)
    os.remove("par-overview.png")
    return

@tree.command(name = "set_base_loss_weight", description = "OWNER ONLY: Sets losses as a score of [x {default: 7.5}] / 6 for pars/averages")
async def set_base_loss_weight(interaction: discord.Interaction, x: int | None):
    wguild = servers[interaction.id]
    view = ui.LayoutView()
    if interaction.user != wguild.owner:
        box = ui.Container(ui.TextDisplay("nuh uh uh"), accent_colour = discord.Colour.red())
        view.add_item(box)
        await interaction.response.send_message(view = view, ephemeral = True, delete_after = 15)
        return
    if x == None:
        x = 7.5
    wguild.BASE_LOSS_WEIGHT = x
    box = ui.Container(ui.TextDisplay("Base loss weight set to %i / 6. Recalibrating database now." % x), accent_colour = discord.Colour.blurple())
    view.add_item(box)
    await interaction.response.send_message(view = view, ephemeral = True, delete_after = 15)
    await prep_guild(wguild)
    box = ui.Container(ui.TextDisplay("Calibration complete. Commands now recognize the new base loss weight." % x), accent_colour = discord.Colour.green())
    view.add_item(box)
    await interaction.response.edit_message(view = view, ephemeral = True, delete_after = 15)
    return

TOKEN = os.environ['TOKEN']

client.run(TOKEN)


# THIS IS A CHANGE
